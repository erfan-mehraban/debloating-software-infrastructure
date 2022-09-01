prefix=$1/strace
mkdir -p $prefix
rm -f $prefix/strace*.out
bash $1/prescript.bash

dool -tdcmlryigp --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out $prefix/strace-dool.csv &
dool_pid=$!
sleep 1

strace -f -t -e trace=file --output=strace.out ./loder/loder $1/tasks.yml --worker 2 --run-time 120s > $prefix/strace-loder.out

kill -s SIGTERM $dool_pid

cat $prefix/strace.out | grep -P "\d+$" | cut -d "\"" -f 2  | sort | uniq > $prefix/strace-file-list.out