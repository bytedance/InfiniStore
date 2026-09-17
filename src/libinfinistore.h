#ifndef LIBINFINISTORE_H
#define LIBINFINISTORE_H

#include <arpa/inet.h>
#include <assert.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include <atomic>
#include <boost/lockfree/spsc_queue.hpp>
#include <deque>
#include <future>
#include <map>
#include <stdexcept>

#include "config.h"
#include "log.h"
#include "protocol.h"
#include "rdma.h"
#include "utils.h"

// Type aliases for clarity
using SendBuffer = Buffer;
using RecvBuffer = Buffer;

enum class WrType {
    BASE,
    RDMA_READ_ACK,
    RDMA_WRITE_ACK,
};

struct rdma_info_base {
   protected:
    WrType wr_type;

   public:
    RecvBuffer *recv_buffer = nullptr;  // Associated receive buffer

    rdma_info_base(WrType wr_type) : wr_type(wr_type) {}
    virtual ~rdma_info_base() = default;
    WrType get_wr_type() const { return wr_type; }
};

struct rdma_write_info : rdma_info_base {
    std::function<void(int)> callback;
    rdma_write_info(std::function<void(int)> callback)
        : rdma_info_base(WrType::RDMA_WRITE_ACK), callback(callback) {}
};

struct rdma_read_info : rdma_info_base {
    // call back function.
    std::function<void(unsigned int, unsigned int[8])> callback;
    rdma_read_info(std::function<void(unsigned int, unsigned int[8])> callback)
        : rdma_info_base(WrType::RDMA_READ_ACK), callback(callback) {}
};

class Connection {
    // tcp socket
    int sock_ = 0;

    struct rdma_device rdma_dev_;
    struct rdma_context ctx_;

    rdma_conn_info_t local_info_;
    rdma_conn_info_t remote_info_;

    // binary tree

    struct cmp {
        bool operator()(const std::pair<uintptr_t, size_t> &a,
                        const std::pair<uintptr_t, size_t> &b) const {
            return a.first < b.first;
        }
    };
    // sort by uintptr_t
    std::map<std::pair<uintptr_t, size_t>, struct ibv_mr *, cmp> local_mr_;

    /*
    This is MAX_RECV_WR not MAX_SEND_WR,
    because server also has the same number of buffers
    */
    boost::lockfree::spsc_queue<SendBuffer *> send_buffers_{MAX_RECV_WR};

    // Receive buffers for RDMA operations, each buffer is 32 bytes
    boost::lockfree::spsc_queue<RecvBuffer *> recv_buffers_{MAX_RECV_WR};

    // struct ibv_comp_channel *comp_channel_ = NULL;
    std::future<void> cq_future_;  // cq thread

    std::atomic<bool> stop_{false};

   public:
    Connection() = default;

    Connection(const Connection &) = delete;
    // destroy the connection
    ~Connection();
    // close cq_handler thread
    void close_conn();
    int init_connection(client_config_t config);
    int setup_rdma(client_config_t config);

    int r_rdma_async(const std::vector<std::string> &keys,
                     const std::vector<uintptr_t> &local_address,
                     const std::vector<uint32_t> &sizes,
                     std::function<void(unsigned int, unsigned int[8])> callback);
    int w_rdma_async(const std::vector<std::string> &keys,
                     const std::vector<uintptr_t> &local_address,
                     const std::vector<uint32_t> &sizes, std::function<void(int)> callback);
    int w_tcp(const std::string &key, void *ptr, size_t size);
    std::vector<unsigned char> *r_tcp(const std::string &key);

    int check_exist(std::string key);
    int get_match_last_index(std::vector<std::string> &keys);
    int delete_keys(const std::vector<std::string> &keys);
    int register_mr(void *base_ptr, size_t ptr_region_size);

    int exchange_conn_info();

    int post_recv_ack(rdma_info_base *info);

    void cq_handler();
    // TODO: refactor to c++ style
    SendBuffer *get_send_buffer();
    void release_send_buffer(SendBuffer *buffer);

    RecvBuffer *get_recv_buffer();
    void release_recv_buffer(RecvBuffer *buffer);

   private:
    bool mr_overlap(void *base_ptr, size_t ptr_region_size);
    struct ibv_mr *mr_contains(void *base_ptr, size_t ptr_region_size);
};

#endif  // LIBINFINISTORE_H
