#ifndef UTILS_H
#define UTILS_H

#include <arpa/inet.h>
#include <stddef.h>

#include <atomic>
#include <boost/intrusive_ptr.hpp>

#include "protocol.h"

int send_exact(int socket, const void *buffer, size_t length);
int recv_exact(int socket, void *buffer, size_t length);

std::string human_readable_gid(union ibv_gid gid);
void print_rdma_conn_info(rdma_conn_info_t *info, bool is_remote);
void signal_handler(int signum);

// print vector is super slow. Use it only for debugging
template <typename T>
void print_vector(T *ptr, size_t size);

class IntrusivePtrTarget {
   public:
    IntrusivePtrTarget() : ref_count(0) {}

    virtual ~IntrusivePtrTarget() = default;

    IntrusivePtrTarget(const IntrusivePtrTarget &) = delete;
    IntrusivePtrTarget &operator=(const IntrusivePtrTarget &) = delete;

    friend void intrusive_ptr_add_ref(IntrusivePtrTarget *p) {
        p->ref_count.fetch_add(1, std::memory_order_relaxed);
    }

    friend void intrusive_ptr_release(IntrusivePtrTarget *p) {
        if (p->ref_count.fetch_sub(1, std::memory_order_acq_rel) == 1) {
            delete p;
        }
    }

   private:
    mutable std::atomic<int> ref_count;
};

#endif  // UTILS_H
