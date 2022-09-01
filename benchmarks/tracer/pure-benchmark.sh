prefix=$1/pure
mkdir -p $prefix
rm -f $prefix/pure*.out
bash $1/prescript.bash

dool -tdcmlryigp --disk-avgqu --disk-avgrq --disk-svctm --disk-tps --disk-util --disk-wait --out $prefix/pure-dool.csv &
dool_pid=$!
sleep 1

./loder/loder $1/tasks.yml --worker 2 --run-time 120s > $prefix/pure-loder.out

kill -s SIGTERM $dool_pid
