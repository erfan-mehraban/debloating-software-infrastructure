sudo echo

rm -f bpftrace*.out

dool -tdcmlryigp --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out bpftrace-dool.out &
dool_pid=$!
sleep 1

sudo ./bpftrace/opensnoop.bt loder > bpftrace.out &
bpftrace_pid=$!
sleep 1
./loder/loder loder/tasks.yml --worker 2 --run-time 120s > bpftrace-loder.out
kill $bpftrace_pid

kill -s SIGTERM $dool_pid

cat bpftrace.out | sort | uniq > bpftrace-file-list.out