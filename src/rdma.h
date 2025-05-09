#ifndef RDMA_H
#define RDMA_H
#include <infiniband/verbs.h>

#include <string>

#include "ibv_helper.h"
#include "protocol.h"

struct rdma_device {
    struct ibv_context *ib_ctx;
    struct ibv_pd *pd;
    int ib_port;
    int gid_index;
    union ibv_gid gid;  // RoCE v2
    uint16_t lid;
    std::string link_type;  // IB or Ethernet
    ibv_mtu active_mtu;
    rdma_device() : ib_ctx(nullptr), pd(nullptr), ib_port(-1), gid_index(-1), lid(-1) {}
};

struct rdma_context {
    // struct rdma_device *rdma_dev;

    struct ibv_comp_channel *comp_channel;
    struct ibv_cq *cq;
    struct ibv_qp *qp;
    uint32_t psn;  // local PSN, randomly generated when creating QP
    rdma_context() : comp_channel(nullptr), cq(nullptr), qp(nullptr) {}
};

int open_rdma_device(std::string dev_name, int ib_port, std::string link_type, int hint_gid_index,
                     struct rdma_device *rdma_dev);
rdma_conn_info_t get_rdma_conn_info(struct rdma_context *ctx, struct rdma_device *rdma_dev);
int init_rdma_context(struct rdma_context *ctx, struct rdma_device *rdma_dev);
int modify_qp_to_init(struct rdma_context *ctx, struct rdma_device *rdma_dev);
int modify_qp_to_rts(struct rdma_context *ctx);
int modify_qp_to_rtr(struct rdma_context *ctx, struct rdma_device *rdma_dev,
                     rdma_conn_info_t *remote_info);

int destroy_rdma_context(struct rdma_context *ctx);
int close_rdma_device(struct rdma_device *rdma_dev);

#endif
