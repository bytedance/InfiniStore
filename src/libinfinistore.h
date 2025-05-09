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

// RDMA send buffer
// because write_cache will be invoked asynchronously,
// so each request will have a standalone send buffer.
struct SendBuffer {
    void *buffer_ = NULL;
    struct ibv_mr *mr_ = NULL;

    SendBuffer(struct ibv_pd *pd, size_t size);
    SendBuffer(const SendBuffer &) = delete;
    ~SendBuffer();
};

enum class WrType {
    BASE,
    RDMA_READ_ACK,
    RDMA_WRITE_ACK,
};

struct rdma_info_base {
   protected:
    WrType wr_type;

   public:
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
    std::function<void(unsigned int)> callback;
    rdma_read_info(std::function<void(unsigned int)> callback)
        : rdma_info_base(WrType::RDMA_READ_ACK), callback(callback) {}
};

class Connection {
    // tcp socket
    int sock_ = 0;

    struct rdma_device rdma_dev_;
    struct rdma_context ctx_;

    rdma_conn_info_t local_info_;
    rdma_conn_info_t remote_info_;

    std::unordered_map<uintptr_t, struct ibv_mr *> local_mr_;

    /*
    This is MAX_RECV_WR not MAX_SEND_WR,
    because server also has the same number of buffers
    */
    boost::lockfree::spsc_queue<SendBuffer *> send_buffers_{MAX_RECV_WR};

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
    int r_rdma_async(const std::vector<std::string> &keys, const std::vector<size_t> offsets,
                     int block_size, void *base_ptr, std::function<void(unsigned int)> callback);
    int w_rdma_async(const std::vector<std::string> &keys, const std::vector<size_t> offsets,
                     int block_size, void *base_ptr, std::function<void(int)> callback);
    int w_tcp(const std::string &key, void *ptr, size_t size);
    std::vector<unsigned char> *r_tcp(const std::string &key);

    int check_exist(std::string key);
    int get_match_last_index(std::vector<std::string> &keys);
    int delete_keys(const std::vector<std::string> &keys);
    int register_mr(void *base_ptr, size_t ptr_region_size);

    int exchange_conn_info();

    void post_recv_ack(rdma_info_base *info);

    void cq_handler();
    // TODO: refactor to c++ style
    SendBuffer *get_send_buffer();
    void release_send_buffer(SendBuffer *buffer);

    SendBuffer *get_recv_buffer();
    void release_recv_buffer(SendBuffer *buffer);
};

#endif  // LIBINFINISTORE_H
