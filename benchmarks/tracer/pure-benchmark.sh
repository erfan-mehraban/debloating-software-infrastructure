rm -f pure*.out

dool -tdcmlryigp --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out pure-dool.out &
dool_pid=$!
sleep 1

./loder/loder loder/tasks.yml --worker 2 --run-time 120s > pure-loder.out

kill -s SIGTERM $dool_pid
