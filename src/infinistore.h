#ifndef INFINISTORE_H
#define INFINISTORE_H
#include <uv.h>

#include <list>

#include "config.h"
#include "log.h"
#include "mempool.h"
#include "utils.h"

extern server_config_t global_config;
extern uv_loop_t *loop;
extern uv_tcp_t server;
// global ibv context
extern struct ibv_context *ib_ctx;
extern struct ibv_pd *pd;
extern MM *mm;

extern int gidx;
extern int lid;
extern uint8_t ib_port;
// local active_mtu attr, after exchanging with remote, we will use the min of the two for path.mtu
extern ibv_mtu active_mtu;

// indicate if the MM extend is in flight
extern bool extend_in_flight;

// PTR is shared by kv_map and inflight_rdma_kv_map
class PTR : public IntrusivePtrTarget {
   public:
    void *ptr = nullptr;
    size_t size;
    int pool_idx;
    std::string key;
    std::list<boost::intrusive_ptr<PTR>>::iterator lru_it;
    PTR(void *ptr, size_t size, int pool_idx, const std::string &key)
        : ptr(ptr), size(size), pool_idx(pool_idx), key(key) {}
    ~PTR() {
        if (ptr) {
            DEBUG("deallocate ptr: {}, size: {}, pool_idx: {}", ptr, size, pool_idx);
            mm->deallocate(ptr, size, pool_idx);
        }
    }
};
extern std::unordered_map<std::string, boost::intrusive_ptr<PTR>> kv_map;
extern std::unordered_map<uintptr_t, boost::intrusive_ptr<PTR>> inflight_rdma_writes;

// global function to bind with python
int register_server(unsigned long loop_ptr, server_config_t config);
void evict_cache(float min_threshold, float max_threshold);
void purge_kv_map();

#endif