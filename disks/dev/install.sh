set -eux

cat > /usr/local/bin/mount_virtiofs <<EOF
#!/bin/bash
sudo mkdir -p /workspace
mount -t virtiofs share_fsdev /workspace
EOF
chmod a+x /usr/local/bin/mount_virtiofs

cat > /etc/profile.d/ossim.sh <<EOF
export OSSIM_BUILD=/build
export OSSIM_OUTPUT=/output
export OSSIM_PREFIX=/prefix

export PATH=\$OSSIM_PREFIX/bin\${PATH:+:\$PATH}
export LD_LIBRARY_PATH=\${OSSIM_PREFIX}/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
export LIBRARY_PATH=\${OSSIM_PREFIX}/lib\${LIBRARY_PATH:+:\$LIBRARY_PATH}
export CPATH=\${OSSIM_PREFIX}/include\${CPATH:+:\$CPATH}
export PKG_CONFIG_PATH=\${OSSIM_PREFIX}/lib/pkgconfig:\${OSSIM_PREFIX}/share/pkgconfig\${PKG_CONFIG_PATH:+:\$PKG_CONFIG_PATH}

export GRPC_CXXFLAGS="-DNOMINMAX -pthread"
export GRPC_LDFLAGS="-lgrpc++ -lgrpc -lgpr -lprotobuf -labsl_log_internal_check_op -labsl_die_if_null -labsl_log_internal_conditions -labsl_log_internal_message -labsl_examine_stack -labsl_log_internal_format -labsl_log_internal_nullguard -labsl_log_internal_structured_proto -labsl_log_internal_proto -labsl_log_internal_log_sink_set -labsl_log_sink -labsl_flags_internal -labsl_flags_marshalling -labsl_flags_reflection -labsl_flags_private_handle_accessor -labsl_flags_commandlineflag -labsl_flags_commandlineflag_internal -labsl_flags_config -labsl_flags_program_name -labsl_log_initialize -labsl_log_internal_globals -labsl_log_globals -labsl_vlog_config_internal -labsl_log_internal_fnmatch -labsl_raw_hash_set -labsl_hash -labsl_city -labsl_low_level_hash -labsl_hashtablez_sampler -labsl_random_distributions -labsl_random_seed_sequences -labsl_random_internal_entropy_pool -labsl_random_internal_randen -labsl_random_internal_randen_hwaes -labsl_random_internal_randen_hwaes_impl -labsl_random_internal_randen_slow -labsl_random_internal_platform -labsl_random_internal_seed_material -labsl_random_seed_gen_exception -labsl_statusor -labsl_status -labsl_cord -labsl_cordz_info -labsl_cord_internal -labsl_cordz_functions -labsl_exponential_biased -labsl_cordz_handle -labsl_crc_cord_state -labsl_crc32c -labsl_crc_internal -labsl_crc_cpu_detect -labsl_leak_check -labsl_strerror -labsl_str_format_internal -labsl_synchronization -labsl_graphcycles_internal -labsl_kernel_timeout_internal -labsl_stacktrace -labsl_symbolize -labsl_debugging_internal -labsl_demangle_internal -labsl_demangle_rust -labsl_decode_rust_punycode -labsl_utf8_for_code_point -labsl_malloc_internal -labsl_tracing_internal -labsl_time -labsl_civil_time -labsl_time_zone -lutf8_validity -lutf8_range -labsl_strings -labsl_strings_internal -labsl_string_view -labsl_int128 -labsl_base -lrt -labsl_spinlock_wait -labsl_throw_delegate -labsl_raw_logging_internal -labsl_log_severity"
EOF

. /etc/profile.d/ossim.sh

DIRS="$OSSIM_BUILD $OSSIM_OUTPUT $OSSIM_PREFIX"

mkdir -p $DIRS
chmod a+rwx $DIRS
