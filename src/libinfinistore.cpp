#include "libinfinistore.h"

#include <arpa/inet.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include <vector>

#include "config.h"
#include "log.h"
#include "protocol.h"
#include "rdma.h"
#include "utils.h"

/*
because python will always hold GIL when doing ~Connection(), which could lead to deadlock,
so we have to explicitly call close() to stop cq_handler.
*/
void Connection::close_conn() {
    if (!stop_ && cq_future_.valid()) {
        stop_ = true;

        // create fake wr to wake up cq thread
        ibv_req_notify_cq(ctx_.cq, 0);
        struct ibv_sge sge;
        memset(&sge, 0, sizeof(sge));
        sge.addr = (uintptr_t)this;
        sge.length = sizeof(*this);
        sge.lkey = 0;

        struct ibv_send_wr send_wr;
        memset(&send_wr, 0, sizeof(send_wr));
        send_wr.wr_id = (uintptr_t)this;
        send_wr.sg_list = &sge;
        send_wr.num_sge = 1;
        send_wr.opcode = IBV_WR_SEND;
        send_wr.send_flags = IBV_SEND_SIGNALED;

        struct ibv_send_wr *bad_send_wr;

        ibv_post_send(ctx_.qp, &send_wr, &bad_send_wr);

        // wait thread done
        cq_future_.get();
    }

    if (sock_) {
        close(sock_);
    }
}

Connection::~Connection() {
    INFO("destroying connection");

    if (!stop_ && cq_future_.valid()) {
        WARN("user should call close() before destroying connection, segmenation fault may occur");
        // throw std::runtime_error("user should call close() before destroying connection");
    }

    SendBuffer *send_buffer;
    while (send_buffers_.pop(send_buffer)) {
        if (send_buffer)
            delete send_buffer;
    }

    RecvBuffer *recv_buffer;
    while (recv_buffers_.pop(recv_buffer)) {
        if (recv_buffer)
            delete recv_buffer;
    }

    for (auto it = local_mr_.begin(); it != local_mr_.end(); it++) {
        ibv_dereg_mr(it->second);
    }
    local_mr_.clear();

    destroy_rdma_context(&ctx_);
    close_rdma_device(&rdma_dev_);
}

void Connection::cq_handler() {
    assert(ctx_.comp_channel != NULL);

    while (!stop_) {
        struct ibv_cq *ev_cq;
        void *ev_ctx;
        int ret = ibv_get_cq_event(ctx_.comp_channel, &ev_cq, &ev_ctx);
        if (ret == 0) {
            ibv_ack_cq_events(ev_cq, 1);
            if (ibv_req_notify_cq(ev_cq, 0)) {
                ERROR("Failed to request CQ notification");
                return;
            }

            struct ibv_wc wc[10] = {};
            int num_completions;
            while ((num_completions = ibv_poll_cq(ctx_.cq, 10, wc)) && num_completions > 0) {
                for (int i = 0; i < num_completions; i++) {
                    if (wc[i].status != IBV_WC_SUCCESS) {
                        // only fake wr will use IBV_WC_SEND
                        // we use it to wake up cq thread and exit
                        if (wc[i].opcode == IBV_WC_SEND) {
                            INFO("cq thread exit");
                            return;
                        }
                        ERROR("Failed status: {}", ibv_wc_status_str(wc[i].status));
                        return;
                    }

                    if (wc[i].opcode ==
                        IBV_WC_SEND) {  // read cache/allocate msg/commit msg: request sent
                        DEBUG("read/write request send {}, ", (uintptr_t)wc[i].wr_id);
                        release_send_buffer((SendBuffer *)wc[i].wr_id);
                    }
                    else if (wc[i].opcode == IBV_WC_RECV) {
                        rdma_info_base *ptr = reinterpret_cast<rdma_info_base *>(wc[i].wr_id);
                        switch (ptr->get_wr_type()) {
                            case WrType::RDMA_READ_ACK: {
                                auto *info = reinterpret_cast<rdma_read_info *>(ptr);
                                // Access the buffer directly when passing to callback
                                info->callback(wc[i].imm_data, reinterpret_cast<unsigned int *>(
                                                                   info->recv_buffer->buffer_));
                                // Release the associated recv buffer
                                if (info->recv_buffer) {
                                    release_recv_buffer(info->recv_buffer);
                                }
                                delete info;
                                break;
                            }
                            case WrType::RDMA_WRITE_ACK: {
                                auto *info = reinterpret_cast<rdma_write_info *>(ptr);
                                info->callback(wc[i].imm_data);
                                // Release the associated recv buffer
                                if (info->recv_buffer) {
                                    release_recv_buffer(info->recv_buffer);
                                }
                                delete info;
                                break;
                            }
                            default:
                                ERROR("Unexpected wr type: {}", (int)ptr->get_wr_type());
                                return;
                        }
                    }
                    else {
                        ERROR("Unexpected opcode: {}", (int)wc[i].opcode);
                        return;
                    }
                }
            }
        }
        else {
            // TODO: graceful shutdown
            if (errno != EINTR) {
                WARN("Failed to get CQ event {}", strerror(errno));
                return;
            }
        }
    }
}

SendBuffer *Connection::get_send_buffer() {
    /*
    if send buffer list is empty,we just report error, and return NULL
    normal user should not have too many inflight requests, so we just report error
    */
    assert(!send_buffers_.empty());

    SendBuffer *buffer;
    assert(send_buffers_.pop(buffer));
    return buffer;
}

void Connection::release_send_buffer(SendBuffer *buffer) { send_buffers_.push(buffer); }

RecvBuffer *Connection::get_recv_buffer() {
    /*
    if recv buffer list is empty,we just report error, and return NULL
    normal user should not have too many inflight requests, so we just report error
    */
    assert(!recv_buffers_.empty());

    RecvBuffer *buffer;
    assert(recv_buffers_.pop(buffer));
    return buffer;
}

void Connection::release_recv_buffer(RecvBuffer *buffer) { recv_buffers_.push(buffer); }

int Connection::setup_rdma(client_config_t config) {
    // if (init_rdma_resources(config) < 0) {
    //     ERROR("Failed to initialize RDMA resources");
    //     return -1;
    // }

    if (open_rdma_device(config.dev_name, config.ib_port, config.link_type, config.hint_gid_index,
                         &rdma_dev_) < 0) {
        ERROR("Failed to open RDMA device");
        return -1;
    }

    if (init_rdma_context(&ctx_, &rdma_dev_) < 0) {
        ERROR("Failed to initialize RDMA context");
        return -1;
    }

    // Exchange RDMA connection information with the server
    if (exchange_conn_info()) {
        return -1;
    }

    print_rdma_conn_info(&remote_info_, true);
    print_rdma_conn_info(&local_info_, false);

    // Modify QP to RTR state
    if (modify_qp_to_rtr(&ctx_, &rdma_dev_, &remote_info_)) {
        ERROR("Failed to modify QP to RTR");
        return -1;
    }

    if (modify_qp_to_rts(&ctx_)) {
        ERROR("Failed to modify QP to RTS");
        return -1;
    }

    /*
    This is MAX_RECV_WR not MAX_SEND_WR,
    because server also has the same number of buffers
    */
    for (int i = 0; i < MAX_RECV_WR; i++) {
        send_buffers_.push(new SendBuffer(rdma_dev_.pd, PROTOCOL_BUFFER_SIZE));
    }

    // Initialize receive buffers (32 bytes each)
    for (int i = 0; i < MAX_RECV_WR; i++) {
        recv_buffers_.push(new RecvBuffer(rdma_dev_.pd, 32));
    }

    stop_ = false;

    cq_future_ = std::async(std::launch::async, [this]() { cq_handler(); });
    return 0;
}

int Connection::init_connection(client_config_t config) {
    signal(SIGSEGV, signal_handler);
    signal(SIGABRT, signal_handler);
    signal(SIGBUS, signal_handler);
    signal(SIGFPE, signal_handler);
    signal(SIGILL, signal_handler);

    struct sockaddr_in serv_addr;
    // create socket
    if ((sock_ = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
        ERROR("Failed to create socket");
        return -1;
    }

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(config.service_port);

    // always connect to localhost
    if (inet_pton(AF_INET, config.host_addr.data(), &serv_addr.sin_addr) <= 0) {
        ERROR("Invalid address/ Address not supported {}", config.host_addr);
        return -1;
    }

    INFO("Connecting to {}:{}", config.host_addr, config.service_port);
    if (connect(sock_, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        ERROR("Failed to connect to server");
        return -1;
    }
    return 0;
}

int Connection::exchange_conn_info() {
    header_t header = {
        .magic = MAGIC,
        .op = OP_RDMA_EXCHANGE,
        .body_size = sizeof(rdma_conn_info_t),
    };

    struct iovec iov[2];
    struct msghdr msg;

    local_info_ = get_rdma_conn_info(&ctx_, &rdma_dev_);

    iov[0].iov_base = &header;
    iov[0].iov_len = FIXED_HEADER_SIZE;
    iov[1].iov_base = &local_info_;
    iov[1].iov_len = sizeof(rdma_conn_info_t);

    memset(&msg, 0, sizeof(msg));
    msg.msg_iov = iov;
    msg.msg_iovlen = 2;

    if (sendmsg(sock_, &msg, 0) < 0) {
        ERROR("Failed to send local connection information");
        return -1;
    }

    int return_code = -1;
    if (recv(sock_, &return_code, RETURN_CODE_SIZE, MSG_WAITALL) < 0) {
        ERROR("Failed to receive return code");
        return -1;
    }

    if (return_code != FINISH) {
        ERROR("Failed to exchange connection information, return code: {}", return_code);
        return -1;
    }

    if (recv(sock_, &remote_info_, sizeof(rdma_conn_info_t), MSG_WAITALL) !=
        sizeof(rdma_conn_info_t)) {
        ERROR("Failed to receive remote connection information");
        return -1;
    }
    return 0;
}

int Connection::check_exist(std::string key) {
    header_t header;
    header = {
        .magic = MAGIC, .op = OP_CHECK_EXIST, .body_size = static_cast<unsigned int>(key.size())};

    struct iovec iov[2];
    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));

    iov[0].iov_base = &header;
    iov[0].iov_len = FIXED_HEADER_SIZE;
    iov[1].iov_base = const_cast<void *>(static_cast<const void *>(key.data()));
    iov[1].iov_len = key.size();
    msg.msg_iov = iov;
    msg.msg_iovlen = 2;

    if (sendmsg(sock_, &msg, 0) < 0) {
        ERROR("Failed to send header and body");
        return -1;
    }

    int return_code = 0;
    if (recv(sock_, &return_code, RETURN_CODE_SIZE, MSG_WAITALL) != RETURN_CODE_SIZE) {
        ERROR("Failed to receive return code");
        return -1;
    }
    if (return_code != FINISH) {
        ERROR("Failed to check exist");
        return -1;
    }

    int exist = 0;
    if (recv(sock_, &exist, sizeof(int), MSG_WAITALL) != sizeof(int)) {
        ERROR("Failed to receive exist");
        return -1;
    }
    return exist;
}

int Connection::get_match_last_index(std::vector<std::string> &keys) {
    INFO("get_match_last_index");

    FlatBufferBuilder builder(64 << 10);

    auto keys_offset = builder.CreateVectorOfStrings(keys);
    auto req = CreateGetMatchLastIndexRequest(builder, keys_offset);
    builder.Finish(req);

    header_t header = {
        .magic = MAGIC,
        .op = OP_GET_MATCH_LAST_IDX,
        .body_size = builder.GetSize(),
    };

    struct iovec iov[2];
    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));

    iov[0].iov_base = &header;
    iov[0].iov_len = FIXED_HEADER_SIZE;
    iov[1].iov_base = builder.GetBufferPointer();
    iov[1].iov_len = builder.GetSize();

    msg.msg_iov = iov;
    msg.msg_iovlen = 2;

    if (sendmsg(sock_, &msg, 0) < 0) {
        ERROR("Failed to send header and body");
        return -1;
    }

    int return_code = 0;
    if (recv(sock_, &return_code, RETURN_CODE_SIZE, MSG_WAITALL) != RETURN_CODE_SIZE) {
        ERROR("Failed to receive return code");
        return -1;
    }
    if (return_code != FINISH) {
        ERROR("Failed to get match last index");
        return -1;
    }

    int last_index = -1;
    if (recv(sock_, &last_index, RETURN_CODE_SIZE, MSG_WAITALL) != RETURN_CODE_SIZE) {
        ERROR("Failed to receive return code");
        return -1;
    }

    return last_index;
}

/**
 *  The function sends the request to delete a list of keys from the store
 *
 *  Input:
 *    keys: the list of the keys to delete
 *
 *  Return:
 *    The count of the keys deleted, -1 if there is an error
 */
int Connection::delete_keys(const std::vector<std::string> &keys) {
    INFO("delete_keys");

    FlatBufferBuilder builder(64 << 10);

    auto keys_offset = builder.CreateVectorOfStrings(keys);
    auto req = CreateDeleteKeysRequest(builder, keys_offset);
    builder.Finish(req);

    header_t header = {
        .magic = MAGIC,
        .op = OP_DELETE_KEYS,
        .body_size = builder.GetSize(),
    };

    struct iovec iov[2];
    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));

    iov[0].iov_base = &header;
    iov[0].iov_len = FIXED_HEADER_SIZE;
    iov[1].iov_base = builder.GetBufferPointer();
    iov[1].iov_len = builder.GetSize();

    msg.msg_iov = iov;
    msg.msg_iovlen = 2;

    if (sendmsg(sock_, &msg, 0) < 0) {
        ERROR("Failed to send header and body for delete_keys message");
        return -1;
    }

    // TODO: Merge the two recv's into one?
    int return_code = 0;
    if (recv(sock_, &return_code, RETURN_CODE_SIZE, MSG_WAITALL) != RETURN_CODE_SIZE) {
        ERROR("Failed to receive return code for delete_keys");
        return -1;
    }
    if (return_code != FINISH) {
        ERROR("Failed to delete keys, error: {}", return_code);
        return -1;
    }

    int count = -1;
    if (recv(sock_, &count, sizeof(count), MSG_WAITALL) != sizeof(count)) {
        ERROR("Failed to receive count of the keys deleted");
        return -1;
    }

    return count;
}

int Connection::post_recv_ack(rdma_info_base *info) {
    RecvBuffer *recv_buffer = get_recv_buffer();

    // Associate the recv_buffer with the info structure
    info->recv_buffer = recv_buffer;

    struct ibv_recv_wr recv_wr {};
    struct ibv_recv_wr *bad_recv_wr = NULL;
    struct ibv_sge sge {};

    sge.addr = (uintptr_t)recv_buffer->buffer_;
    sge.length = 32;
    sge.lkey = recv_buffer->mr_->lkey;

    recv_wr.wr_id = (uintptr_t)info;
    recv_wr.next = NULL;
    recv_wr.sg_list = &sge;
    recv_wr.num_sge = 1;

    int ret = ibv_post_recv(ctx_.qp, &recv_wr, &bad_recv_wr);
    if (ret) {
        ERROR("Failed to post recv wr :{}", strerror(ret));
        // Release the buffer back to the pool on error
        release_recv_buffer(recv_buffer);
        info->recv_buffer = nullptr;
    }
    return ret;
}

std::vector<unsigned char> *Connection::r_tcp(const std::string &key) {
    FlatBufferBuilder builder(64 << 10);
    auto req = CreateTCPPayloadRequestDirect(builder, key.c_str(), 0, OP_TCP_GET);
    builder.Finish(req);

    header_t header = {
        .magic = MAGIC,
        .op = OP_TCP_PAYLOAD,
        .body_size = builder.GetSize(),
    };

    struct iovec iov[2];
    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));

    iov[0].iov_base = &header;
    iov[0].iov_len = FIXED_HEADER_SIZE;
    iov[1].iov_base = builder.GetBufferPointer();
    iov[1].iov_len = builder.GetSize();

    msg.msg_iov = iov;
    msg.msg_iovlen = 2;

    if (sendmsg(sock_, &msg, 0) < 0) {
        ERROR("r_tcp: Failed to send header");
        return nullptr;
    }

    uint32_t buf[2];
    if (recv(sock_, &buf, RETURN_CODE_SIZE * 2, MSG_WAITALL) != RETURN_CODE_SIZE * 2) {
        ERROR("r_tcp: Failed to receive return code");
        return nullptr;
    }

    int return_code = buf[0];
    int size = buf[1];

    if (return_code != FINISH) {
        ERROR("r_tcp: Failed to get value, return code: {}", key, return_code);
        return nullptr;
    }

    if (size == 0) {
        ERROR("r_tcp: size is 0");
        return nullptr;
    }

    auto ret_buf = new std::vector<unsigned char>(size);

    if (recv(sock_, ret_buf->data(), size, MSG_WAITALL) != size) {
        ERROR("r_tcp: Failed to receive payload");
        return nullptr;
    }
    return ret_buf;
}

int Connection::w_tcp(const std::string &key, void *ptr, size_t size) {
    assert(ptr != NULL);

    FlatBufferBuilder builder(64 << 10);
    auto req = CreateTCPPayloadRequestDirect(builder, key.c_str(), size, OP_TCP_PUT);
    builder.Finish(req);

    header_t header = {
        .magic = MAGIC,
        .op = OP_TCP_PAYLOAD,
        .body_size = builder.GetSize(),
    };

    struct iovec iov[2];
    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));

    iov[0].iov_base = &header;
    iov[0].iov_len = FIXED_HEADER_SIZE;
    iov[1].iov_base = builder.GetBufferPointer();
    iov[1].iov_len = builder.GetSize();

    msg.msg_iov = iov;
    msg.msg_iovlen = 2;

    if (sendmsg(sock_, &msg, MSG_MORE) < 0) {
        ERROR("w_tcp: Failed to send header");
        return -1;
    }

    // reuse iov[0] and msghdr
    iov[0].iov_base = ptr;
    iov[0].iov_len = size;
    msg.msg_iov = iov;
    msg.msg_iovlen = 1;
    if (sendmsg(sock_, &msg, 0) < 0) {
        ERROR("w_tcp: Failed to send payload");
        return -1;
    }

    int return_code = 0;
    if (recv(sock_, &return_code, RETURN_CODE_SIZE, MSG_WAITALL) != RETURN_CODE_SIZE) {
        ERROR("w_tcp: Failed to receive return code");
        return -1;
    }
    if (return_code != FINISH) {
        ERROR("w_tcp: Failed to put key: {}, return code: {}", key, return_code);
        return -1;
    }

    return 0;
}

int Connection::w_rdma_async(const std::vector<std::string> &keys,
                             const std::vector<uintptr_t> &local_address,
                             const std::vector<uint32_t> &block_sizes,
                             std::function<void(int)> callback) {
    assert(local_address.size() > 0);
    assert(local_address.size() == keys.size());
    assert(keys.size() == block_sizes.size());

    SendBuffer *send_buffer = get_send_buffer();
    FixedBufferAllocator allocator(send_buffer->buffer_, PROTOCOL_BUFFER_SIZE);
    FlatBufferBuilder builder(64 << 10, &allocator);
    auto keys_offset = builder.CreateVectorOfStrings(keys);
    auto remote_addrs_offset = builder.CreateVector(local_address);
    auto sizes_offset = builder.CreateVector(block_sizes);

    // build rkey array
    std::vector<uint32_t> rkeys;
    for (size_t i = 0; i < local_address.size(); i++) {
        uintptr_t address = local_address[i];
        size_t size = block_sizes[i];
        auto mr = mr_contains((void *)address, size);
        rkeys.push_back(mr->rkey);
    }
    auto rkeys_offset = builder.CreateVector(rkeys);
    auto req = CreateRemoteMetaRequest(builder, keys_offset, sizes_offset, rkeys_offset,
                                       remote_addrs_offset, OP_RDMA_WRITE);
    builder.Finish(req);

    // post recv msg first
    auto *info = new rdma_write_info(callback);
    if (post_recv_ack(info) < 0) {
        ERROR("Failed to post recv ack for RDMA write");
        delete info;  // Clean up if post_recv_ack fails
        return -1;
    }

    // send msg
    struct ibv_sge sge {};
    struct ibv_send_wr wr {};
    struct ibv_send_wr *bad_wr = NULL;
    sge.addr = (uintptr_t)builder.GetBufferPointer();
    sge.length = builder.GetSize();
    sge.lkey = send_buffer->mr_->lkey;

    wr.wr_id = (uintptr_t)send_buffer;
    wr.opcode = IBV_WR_SEND;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    wr.send_flags = IBV_SEND_SIGNALED;

    int ret = ibv_post_send(ctx_.qp, &wr, &bad_wr);
    if (ret) {
        ERROR("Failed to post RDMA send :{}", strerror(ret));
        return -1;
    }

    return 0;
}

int Connection::r_rdma_async(const std::vector<std::string> &keys,
                             const std::vector<uintptr_t> &local_address,
                             const std::vector<uint32_t> &block_sizes,
                             std::function<void(unsigned int, unsigned int[8])> callback) {
    assert(local_address.size() == keys.size());
    assert(block_sizes.size() == keys.size());

    SendBuffer *send_buffer = get_send_buffer();
    FixedBufferAllocator allocator(send_buffer->buffer_, PROTOCOL_BUFFER_SIZE);
    FlatBufferBuilder builder(64 << 10, &allocator);
    auto keys_offset = builder.CreateVectorOfStrings(keys);
    auto remote_addrs_offset = builder.CreateVector(local_address);
    auto sizes_offset = builder.CreateVector(block_sizes);

    // build rkey array
    std::vector<uint32_t> rkeys;
    for (size_t i = 0; i < local_address.size(); i++) {
        uintptr_t address = local_address[i];
        size_t size = block_sizes[i];
        auto mr = mr_contains((void *)address, size);
        rkeys.push_back(mr->rkey);
    }
    auto rkeys_offset = builder.CreateVector(rkeys);
    auto req = CreateRemoteMetaRequest(builder, keys_offset, sizes_offset, rkeys_offset,
                                       remote_addrs_offset, OP_RDMA_READ);
    builder.Finish(req);

    auto *info = new rdma_read_info(callback);
    post_recv_ack(info);

    // send RDMA request
    struct ibv_sge sge {};
    sge.addr = (uintptr_t)builder.GetBufferPointer();
    sge.length = builder.GetSize();
    sge.lkey = send_buffer->mr_->lkey;

    struct ibv_send_wr wr {};
    struct ibv_send_wr *bad_wr = NULL;

    wr.wr_id = (uintptr_t)send_buffer;
    wr.opcode = IBV_WR_SEND;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    wr.send_flags = IBV_SEND_SIGNALED;

    int ret;
    ret = ibv_post_send(ctx_.qp, &wr, &bad_wr);

    if (ret) {
        ERROR("Failed to post RDMA send :{}", strerror(ret));
        return -1;
    }

    return 0;
}

struct ibv_mr *Connection::mr_contains(void *base_ptr, size_t ptr_region_size) {
    assert(base_ptr != NULL);

    uintptr_t base_ptr_int = (uintptr_t)base_ptr;
    uintptr_t end_ptr_int = base_ptr_int + ptr_region_size;

    auto it = local_mr_.upper_bound({base_ptr_int, 0});
    if (it != local_mr_.begin()) {
        --it;
        if (it->first.first <= base_ptr_int && it->first.first + it->first.second >= end_ptr_int) {
            return it->second;
        }
    }
    return nullptr;
}

bool Connection::mr_overlap(void *base_ptr, size_t ptr_region_size) {
    assert(base_ptr != NULL);

    uintptr_t base_ptr_int = (uintptr_t)base_ptr;
    uintptr_t end_ptr_int = base_ptr_int + ptr_region_size;

    auto it = local_mr_.lower_bound({base_ptr_int, 0});
    if (it != local_mr_.end()) {
        if (it->first.first < end_ptr_int) {
            // corner case: allow exactly the same region
            if (base_ptr_int == it->first.first &&
                base_ptr_int + ptr_region_size == it->first.first + it->first.second) {
                WARN("overlap with existing mr, but same region");
                return false;
            }
            return true;
        }
    }

    // check the last element
    if (it != local_mr_.begin()) {
        --it;
        size_t prev_end = it->first.first + it->first.second;
        if (base_ptr_int < prev_end) {
            return true;
        }
    }

    return false;
}

int Connection::register_mr(void *base_ptr, size_t ptr_region_size) {
    assert(base_ptr != NULL);

    // detect overlap of _local_mr_
    if (mr_overlap(base_ptr, ptr_region_size)) {
        ERROR("overlap with existing mr");
        return -1;
    }

    struct ibv_mr *mr;
    mr = ibv_reg_mr(rdma_dev_.pd, base_ptr, ptr_region_size,
                    IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ);
    if (!mr) {
        ERROR("Failed to register memory regions, size: {}", ptr_region_size);
        return -1;
    }
    INFO("register mr done for base_ptr: {}, size: {}", (uintptr_t)base_ptr, ptr_region_size);
    local_mr_.insert({{(uintptr_t)base_ptr, ptr_region_size}, mr});
    return 0;
}
