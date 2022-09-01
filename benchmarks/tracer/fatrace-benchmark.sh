prefix=$1/fatrace
mkdir -p $prefix
sudo echo
rm -f $prefix/fatrace*.out
bash $1/prescript.bash

dool -tdcmlryigp --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out $prefix/fatrace-dool.csv &
dool_pid=$!
echo $dool_pid
sleep 1

sudo fatrace --command loder -o $prefix/fatrace.out &
fatrace_pid=$!
sleep 1
./loder/loder $1/tasks.yml --worker 2 --run-time 1  120s > $prefix/fatrace-loder.out
kill $fatrace_pid

kill -s SIGTERM $dool_pid

cat $prefix/fatrace.out | cut -d' ' -f 3 | sort | uniq > $prefix/fatrace-file-list.out