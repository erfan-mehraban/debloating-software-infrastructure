rm -f strace*.out

dool -tdcmlryigp --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out strace-dool.out &
dool_pid=$!
sleep 1

strace -f -t -e trace=file --output=strace.out ./loder/loder loder/tasks.yml --worker 2 --run-time 120s > strace-loder.out

kill -s SIGTERM $dool_pid

cat strace.out | grep -P "\d+$" | cut -d "\"" -f 2  | sort | uniq > strace-file-list.out