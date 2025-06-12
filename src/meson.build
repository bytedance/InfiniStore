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

add_project_arguments('-Wno-unused-parameter', language: 'cpp')


python3 = import('python').find_installation('python3', pure: false)

# C/C++ compiler interface
cc = meson.get_compiler('cpp')

fb_sources = [
  'meta_request.fbs',
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
ibverbs_dep  = dependency('libibverbs', required: true)
dw_dep = dependency('libdw', required: true)
dl_dep = cc.find_library('dl', required: true)
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
  dependencies: [
    pybind_dep,
    libuv_dep,
    fmt_dep,
    ibverbs_dep,
    dl_dep,
    dw_dep
    ],
  install: true
)