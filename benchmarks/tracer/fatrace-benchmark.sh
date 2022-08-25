sudo echo
rm -f *.out

dool -lcmdryTtg --full --profile --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out fatrace-dool.out &
dool_pid=$!
echo $dool_pid
sleep 1

sudo fatrace --command loder -o fatrace.out &
fatrace_pid=$!
sleep 1
./loder/loder loder/tasks.yml --worker 2 --run-time 30s > fatrace-loder.out
kill $fatrace_pid

kill $dool_pid

cat fatrace.out | cut -d' ' -f 3 | sort | uniq > fatrace-file-list.out