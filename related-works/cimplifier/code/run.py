import sys
import json
import subprocess
import shlex
from time import sleep
from itertools import chain
from docker import Client

def make_docker_cmd(img, name, cmd, vols, netns=None, ports=None, env=None, cwd=None):
    if not env:
        env = {}
    envparams = ' '.join('-e %s=%s' % item for item in env.items())
    volparams = ' '.join('-v %s:%s' % (i['Source'], i['Destination']) for i in
        vols)
    return 'docker run --name {n} {net} {ep} {vp} {ports} {wd} -d {img} {cmd}'.format(
            n=(name+'_'+img),
            net=('--net {}'.format(netns) if netns else ''),
            ep=envparams,
            vp=volparams,
            ports=(ports if ports else ''),
            wd=('-w {}'.format(cwd) if cwd else ''),
            img=img,
            cmd=cmd)

def make_commands(filename, runprefix, ports=None):
    with open(filename) as f:
        config = json.load(f)
    orig = config['original_container']
    new_cntnrs = config['config']
    for mainname, main_config in new_cntnrs.items():
        if main_config['ismain']:
            break
    del new_cntnrs[mainname]

    netns = None
    for name, cnf in new_cntnrs.items():
        allvols = chain(cnf['vols'], cnf['exec_vols'], cnf['shared_vols'])
        cmd = make_docker_cmd(name, runprefix, cnf['cmd'], allvols, netns,
                ports)
        print(cmd)
        cntnr = subprocess.check_output(shlex.split(cmd))
        cntnr = cntnr.strip()
        if netns is None:
            netns = 'container:' + cntnr.decode("utf-8")
            ports = None

    allvols = chain(main_config['vols'], main_config['exec_vols'],
            main_config['shared_vols'])
    maincmd = make_docker_cmd(mainname, runprefix,'', allvols, netns)
    print('run it yourself')
    print(maincmd)

if __name__ == '__main__':
    make_commands(*sys.argv[1:])

