prefix=$1/bpftrace
mkdir -p $prefix
sudo echo
rm -f $prefix/bpftrace*.out
rm -f $prefix/bpftrace*.csv
bash $1/prescript.bash

dool -tdcmlryigp --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out $prefix/bpftrace-dool.csv &
dool_pid=$!
sleep 1

sudo ./bpftrace/opensnoop.bt loder > $prefix/bpftrace.out &
bpftrace_pid=$!
sleep 1
./loder/loder $1/tasks.yml --worker 2 --run-time 120s > $prefix/bpftrace-loder.out
kill $bpftrace_pid

kill -s SIGTERM $dool_pid

cat $prefix/bpftrace.out | sort | uniq > $prefix/bpftrace-file-list.out