project('infinistore',
['cpp'],
version: '0.0.0',
default_options: [
  'buildtype=release',
  'cpp_std=c++17',
  'warning_level=2',  # -Wall
  'optimization=3',   # -O3
  'debug=true'        # -g
])

python3 = import('python').find_installation('python3', pure: false)

# C/C++ compiler interface
cc = meson.get_compiler('cpp')

fb_sources = [
  'meta_request.fbs',
  'allocate_response.fbs',
  'delete_keys.fbs',
  'get_match_last_index.fbs',
  'tcp_payload_request.fbs'
]

flatc = find_program('flatc', required: true)

generated_headers = []

foreach fb_source : fb_sources
  fb_name = fb_source.split('.')[0]
  header_name = fb_name + '_generated.h'
  generated_headers += custom_target(
    fb_name + '_gen',
    input: fb_source,
    output: header_name,
    command: [
      flatc,
      '--cpp',
      '@INPUT@',
    ],
  )
endforeach

# External library dependencies
pybind_dep = dependency('pybind11', required: true)
libuv_dep     = dependency('libuv', required: true)
fmt_dep       = dependency('fmt', required: true)
boost_stack_dep   = dependency('boost', modules: ['stacktrace_basic'], required: true)
ibverbs_dep  = dependency('libibverbs', required: true)

# Source files for the extension
ext_sources = [
  'libinfinistore.cpp',
  'utils.cpp',
  'protocol.cpp',
  'infinistore.cpp',
  'log.cpp',
  'ibv_helper.cpp',
  'mempool.cpp',
  'rdma.cpp',
  'pybind.cpp'
]


# Build the Python extension module
python3.extension_module('_infinistore',
  sources: ext_sources + generated_headers,
  dependencies: [pybind_dep, libuv_dep, fmt_dep, boost_stack_dep, ibverbs_dep],
  install: true
)

rdma_test_wrappers = [
  'ibv_get_device_list',
  'ibv_get_device_name',
  'ibv_open_device',
  'ibv_query_port',
  'ibv_query_gid',
  'ibv_alloc_pd',
  'ibv_dealloc_pd',
  'ibv_close_device',
]
rdma_test_link_args = []
foreach symbol : rdma_test_wrappers
  rdma_test_link_args += '-Wl,--wrap=' + symbol
endforeach

rdma_device_test = executable('test_rdma_device',
  sources: ['test_rdma_device.cpp', 'rdma.cpp', 'utils.cpp'] + generated_headers,
  dependencies: [fmt_dep, boost_stack_dep, ibverbs_dep],
  link_args: rdma_test_link_args,
  build_by_default: false,
)
foreach port : ['1', '2']
  foreach hint : ['-1', '3']
    test('rdma-gid-port-' + port + '-hint-' + hint, rdma_device_test,
      args: [port, hint],
      suite: 'rdma-device',
    )
  endforeach
endforeach

protocol_test = executable('test_protocol',
  sources: ['test_protocol.cpp', 'protocol.cpp'] + generated_headers,
  build_by_default: false,
)
test('protocol-header-validation', protocol_test, suite: 'protocol')
