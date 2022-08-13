#! /bin/bash
# usage: bash main.bash image-name tag whitelist-file
# known issue: essential gnome tools like bash/ls/... doesnt work properly
# https://github.com/opencontainers/image-spec/blob/main/spec.md

set -e
set -x

skopeo copy docker-daemon:$1:$2 oci:$1-oci:latest
umoci unpack --rootless --image $1-oci:$2 $1-$2-bundle

export HERE=$PWD
cd $1-$2-bundle
cat $HERE/$3 | while read line
do
    echo $line
    mkdir -p rootfs-slim`dirname $line`
    cp -r rootfs$line rootfs-slim$line
done
cd $HERE

umoci init --layout $1-$2-slim
umoci new --image $1-$2-slim:latest
umoci insert --rootless --image $1-$2-slim:latest $1-$2-bundle/rootfs-slim /
umoci unpack --rootless --image $1-$2-slim:latest $1-$2-slim-bundle
umoci raw config --rootless --rootfs rootfs --image $1-oci:$2 $1-$2-slim-bundle/config.json
umoci repack --image $1-$2-slim:$2 $1-$2-slim-bundle
umoci gc --layout $1-$2-slim

# skopeo copy oci:$1-$2-slim:latest docker-daemon:$1-slim:$2
# rm -rf $1-*

set +x