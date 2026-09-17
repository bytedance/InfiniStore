#include <cstdio>
#include <limits>

#include "protocol.h"

struct HeaderCase {
    const char *name;
    header_t header;
    int expected;
};

int main() {
    const HeaderCase cases[] = {
        {"valid", {MAGIC, OP_CHECK_EXIST, 1}, 0},
        {"maximum body", {MAGIC, OP_CHECK_EXIST, PROTOCOL_BUFFER_SIZE}, 0},
        {"zero body", {MAGIC, OP_CHECK_EXIST, 0}, 0},
        {"oversized body", {MAGIC, OP_CHECK_EXIST, PROTOCOL_BUFFER_SIZE + 1}, INVALID_REQ},
        {"maximum integer body",
         {MAGIC, OP_CHECK_EXIST, std::numeric_limits<unsigned int>::max()},
         INVALID_REQ},
        {"invalid magic", {0, OP_CHECK_EXIST, 1}, INVALID_REQ},
    };

    for (const auto &test : cases) {
        int actual = verify_header(&test.header);
        if (actual != test.expected) {
            std::fprintf(stderr, "%s: expected %d, got %d\n", test.name, test.expected, actual);
            return 1;
        }
    }
    return 0;
}
