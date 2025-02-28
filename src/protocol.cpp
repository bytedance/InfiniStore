#include "protocol.h"

#include <unordered_map>

std::unordered_map<char, std::string> op_map = {{OP_RDMA_EXCHANGE, "RDMA_EXCHANGE"},
                                                {OP_RDMA_READ, "RDMA_READ"},
                                                {OP_RDMA_WRITE_COMMIT, "RDMA_WRITE_COMMIT"},
                                                {OP_RDMA_ALLOCATE, "RDMA_ALLOCATE"},
                                                {OP_CHECK_EXIST, "CHECK_EXIST"},
                                                {OP_GET_MATCH_LAST_IDX, "GET_MATCH_LAST_IDX"},
                                                {OP_DELETE_KEYS, "DELETE_KEYS"}};
std::string op_name(char op_code) {
    auto it = op_map.find(op_code);
    if (it != op_map.end()) {
        return it->second;
    }
    return "UNKNOWN";
}

uint8_t* FixedBufferAllocator::allocate(size_t size) {
    if (offset_ + size > size_) {
        throw std::runtime_error("Buffer overflow in FixedBufferAllocator");
    }
    uint8_t* ptr = static_cast<uint8_t*>(buffer_) + offset_;
    offset_ += size;
    return ptr;
}

void FixedBufferAllocator::deallocate(uint8_t*, size_t) {
    // no-op
}

bool is_fake_remote_block(remote_block_t& block) {
    return block.remote_addr == 0 && block.rkey == 0;
}
