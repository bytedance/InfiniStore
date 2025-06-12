#include <pybind11/functional.h>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <iostream>
#include <memory>
#include <string>
#include <tuple>
#include <vector>

#include "config.h"
#include "infinistore.h"
#include "libinfinistore.h"
#include "log.h"

namespace py = pybind11;

extern int register_server(unsigned long loop_ptr, server_config_t config);

// See https://github.com/pybind/pybind11/issues/1042#issuecomment-642215028
// as_pyarray is a helper function to convert a C++ sequence to a numpy array and zero-copy
template <typename Sequence>
inline py::array_t<typename Sequence::value_type> as_pyarray(Sequence &&seq) {
    // Move entire object to heap. Memory handled via Python capsule
    Sequence *seq_ptr = new Sequence(std::move(seq));
    // Capsule shall delete sequence object when done
    auto capsule = py::capsule(seq_ptr, [](void *p) { delete reinterpret_cast<Sequence *>(p); });

    return py::array(static_cast<py::ssize_t>(seq_ptr->size()),  // shape of array
                     seq_ptr->data(),  // c-style contiguous strides for Sequence
                     capsule           // numpy array references this parent
    );
}

PYBIND11_MODULE(_infinistore, m) {
    // client side
    py::class_<client_config_t>(m, "ClientConfig")
        .def(py::init<>())
        .def_readwrite("service_port", &client_config_t::service_port)
        .def_readwrite("log_level", &client_config_t::log_level)
        .def_readwrite("dev_name", &client_config_t::dev_name)
        .def_readwrite("ib_port", &client_config_t::ib_port)
        .def_readwrite("link_type", &client_config_t::link_type)
        .def_readwrite("host_addr", &client_config_t::host_addr)
        .def_readwrite("hint_gid_index", &client_config_t::hint_gid_index);

    py::class_<Connection, std::shared_ptr<Connection>>(m, "Connection")
        .def(py::init<>())
        .def("close", &Connection::close_conn, py::call_guard<py::gil_scoped_release>(),
             "close the connection")
        .def(
            "w_tcp",
            [](Connection &self, const std::string &key, uintptr_t ptr, size_t size) {
                return self.w_tcp(key, (void *)ptr, size);
            },
            py::call_guard<py::gil_scoped_release>(), "Write remote memory using TCP")
        .def(
            "r_tcp",
            [](Connection &self, const std::string &key) {
                auto vector_ptr = self.r_tcp(key);
                py::gil_scoped_acquire acquire;
                return as_pyarray(std::move(*vector_ptr));
            },
            py::call_guard<py::gil_scoped_release>(), "Read remote memory using TCP")
        .def(
            "w_rdma_async",
            [](Connection &self, const std::vector<std::string> &keys,
               const std::vector<size_t> offsets, int block_size, uintptr_t base_ptr,
               std::function<void(int)> callback) {
                std::vector<uint64_t> local_address;
                for (size_t i = 0; i < keys.size(); i++) {
                    local_address.push_back(base_ptr + offsets[i]);
                }
                std::vector<uint32_t> sizes(keys.size(), block_size);

                return self.w_rdma_async(keys, local_address, sizes, callback);
            },
            py::call_guard<py::gil_scoped_release>(), "write rdma async")
        .def(
            "w_rdma_async2",
            [](Connection &self, const std::vector<std::string> &keys,
               const std::vector<uintptr_t> &local_address,
               const std::vector<uint32_t> &block_sizes, std::function<void(int)> callback) {
                return self.w_rdma_async(keys, local_address, block_sizes, callback);
            },
            py::call_guard<py::gil_scoped_release>(), "write rdma async2")
        .def(
            "r_rdma_async",
            [](Connection &self, const std::vector<std::string> &keys,
               const std::vector<size_t> offsets, int block_size, uintptr_t base_ptr,
               std::function<void(int, std::vector<unsigned int>)> py_callback) {
                auto cpp_callback = [py_callback](unsigned int code, unsigned int payload[8]) {
                    std::vector<unsigned int> py_payload(payload, payload + 8);
                    py_callback(code, py_payload);
                };
                std::vector<uint32_t> sizes(keys.size(), block_size);
                std::vector<uint64_t> local_address;
                for (size_t i = 0; i < keys.size(); i++) {
                    local_address.push_back((uintptr_t)base_ptr + offsets[i]);
                }
                return self.r_rdma_async(keys, local_address, sizes, cpp_callback);
            },
            py::call_guard<py::gil_scoped_release>(), "Read remote memory asynchronously")
        .def(
            "r_rdma_async2",
            [](Connection &self, const std::vector<std::string> &keys,
               const std::vector<uint64_t> &local_address, const std::vector<uint32_t> &block_sizes,
               std::function<void(int, std::vector<unsigned int>)> py_callback) {
                auto cpp_callback = [py_callback](unsigned int code, unsigned int payload[8]) {
                    std::vector<unsigned int> py_payload(payload, payload + 8);
                    py_callback(code, py_payload);
                };
                return self.r_rdma_async(keys, local_address, block_sizes, cpp_callback);
            },
            py::call_guard<py::gil_scoped_release>(), "Read remote memory asynchronously2")
        .def("init_connection", &Connection::init_connection,
             py::call_guard<py::gil_scoped_release>(), "init connection")
        .def("setup_rdma", &Connection::setup_rdma, py::call_guard<py::gil_scoped_release>(),
             "setup rdma connection")
        .def("check_exist", &Connection::check_exist, py::call_guard<py::gil_scoped_release>(),
             "check if the key exists in the store")
        .def("get_match_last_index", &Connection::get_match_last_index,
             py::call_guard<py::gil_scoped_release>(),
             "get the last index of a key list which is in the store")
        .def("delete_keys", &Connection::delete_keys, py::call_guard<py::gil_scoped_release>(),
             "delete a list of keys which are in store")
        .def(
            "register_mr",
            [](Connection &self, uintptr_t ptr, size_t ptr_region_size) {
                return self.register_mr((void *)ptr, ptr_region_size);
            },
            py::call_guard<py::gil_scoped_release>(), "register memory region");

    // server side
    py::class_<server_config_t>(m, "ServerConfig")
        .def(py::init<>())
        .def_readwrite("service_port", &ServerConfig::service_port)
        .def_readwrite("log_level", &ServerConfig::log_level)
        .def_readwrite("dev_name", &ServerConfig::dev_name)
        .def_readwrite("ib_port", &ServerConfig::ib_port)
        .def_readwrite("link_type", &ServerConfig::link_type)
        .def_readwrite("prealloc_size", &ServerConfig::prealloc_size)
        .def_readwrite("minimal_allocate_size", &ServerConfig::minimal_allocate_size)
        .def_readwrite("auto_increase", &ServerConfig::auto_increase)
        .def_readwrite("hint_gid_index", &ServerConfig::hint_gid_index);
    m.def(
        "purge_kv_map", []() { kv_map.clear(); }, "purge kv map");
    m.def(
        "get_kvmap_len", []() { return kv_map.size(); }, "get kv map size");
    m.def("register_server", &register_server, "register the server");
    m.def("evict_cache", &evict_cache, "evict the mempool");

    // //both side
    m.def("log_msg", &log_msg, "log");
    m.def("set_log_level", &set_log_level, "set log level");
}
