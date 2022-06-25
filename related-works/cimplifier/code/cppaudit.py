#!/bin/env python3

import os
import sys
from collections import defaultdict

import auparse
from auparse import AuEvent, AuParser

childparent_map = {}
fdpath_map = {}
read_files = defaultdict(set)

class AuException(Exception):
    pass

class SysCallRec(object):
    pass

def _syscallrec_parse(parser):
    rec = SysCallRec()
    print(parser.get_record_text())
    parser.find_field('syscall')
    rec.syscall = parser.interpret_field()
    parser.find_field('exit')
    rec.exit = parser.get_field_int()
    rec.a0 = parser.find_field('a0')
    rec.a1 = parser.find_field('a1')
    rec.a2 = parser.find_field('a2')
    rec.a3 = parser.find_field('a3')
    parser.find_field('ppid')
    rec.ppid = parser.get_field_int()
    parser.find_field('pid')
    rec.pid = parser.get_field_int()
    return rec

def tofd(fdstr):
    if fdstr.endswith('ffffff9c'):
        return 'AT_FDCWD'
    return int(fdstr)

def _single_path_parse(parser):
    name = None
    while parser.next_record():
        rectype = parser.get_type_name()
        if rectype == 'CWD':
            parser.find_field('cwd')
            cwd = parser.get_field_str()
            if cwd == '(null)':
                cwd = ''
            else:
                cwd = cwd[1:-1]
        if rectype == 'PATH':
            txt = parser.get_record_text().rstrip()
            if (txt.endswith('nametype=NORMAL') or
                    txt.endswith('nametype=DELETE')):
                parser.find_field('name')
                name = parser.get_field_str()
                if name == '(null)':
                    name = ''
                else:
                    # we get a quoted name, so unquote it
                    name = name[1:-1]
                parser.find_field('inode')
                inode = parser.get_field_int()
                parser.find_field('mode')
                filetype = parser.interpret_field().split(',')[0]
    if name is not None:
        return (cwd, name, inode, filetype)

# TODO: deduplicate code in these two functions
def _multi_path_parse(parser):
    paths = []
    while parser.next_record():
        rectype = parser.get_type_name()
        if rectype == 'CWD':
            parser.find_field('cwd')
            cwd = parser.get_field_str()
            if cwd == '(null)':
                cwd = ''
            else:
                cwd = cwd[1:-1]
        if rectype == 'PATH':
            txt = parser.get_record_text().rstrip()
            if (txt.endswith('nametype=NORMAL') or
                    txt.endswith('nametype=DELETE')):
                parser.find_field('name')
                name = parser.get_field_str()
                if name == '(null)':
                    name = ''
                else:
                    # we get a quoted name, so unquote it
                    name = name[1:-1]
                parser.find_field('inode')
                inode = parser.get_field_int()
                parser.find_field('mode')
                filetype = parser.interpret_field().split(',')[0]
                paths.append((name, inode, filetype))
    return (cwd, paths)


def cppauparse(initpid, parser=None):
    if parser is None:
        parser = make_system_parser()
    # first get to the point where we are inside the container
    parser.search_add_expression(
            r'(syscall i= "execve") && (pid r= {}) && (success r= "yes") && (comm i!= "exe")'.format(initpid),
            auparse.AUSEARCH_RULE_CLEAR
            )
    parser.search_next_event()
    print(parser.get_record_text())
    # we are now at the point that the container command was just executed
    parser.search_add_expression(
            r'(\record_type == "SYSCALL") && (success r= "yes")',
            auparse.AUSEARCH_RULE_CLEAR
            )
    parser.search_set_stop(auparse.AUSEARCH_STOP_EVENT)
    while True:
        parser.first_record()
        parser.first_field()
        screc = _syscallrec_parse(parser)
        syscall = screc.syscall
        pid = screc.pid
        childparent_map[pid] = screc.ppid

        # the clone/fork syscalls
        if syscall == 'clone' or syscall == 'fork' or syscall == 'vfork':
            # the exit code is the pid in the container's namespace and is not
            # useful to us when dealing with containers
            pass
            # childparent_map[screc.exit] = pid

        if syscall == 'execve':
            cwd, paths = _multi_path_parse(parser)
            for path, inode, filetype in paths:
                fullpath = os.path.join(cwd, path)
                read_files[pid].add(fullpath)

        # open calls
        elif syscall == 'open':
            ret = _single_path_parse(parser)
            if ret:
                cwd, path, _, filetype = ret
                fullpath = os.path.join(cwd, path)
                read_files[pid].add(fullpath)
                fdpath_map[(pid, screc.exit)] = fullpath
        elif syscall == 'openat':
            ret = _single_path_parse(parser)
            if ret:
                cwd, path, _, filetype = ret
                fd = tofd(screc.a0)
                # the constants below denote AT_FDCWD
                if fd == 'AT_FDCWD':
                    fullpath = os.path.join(cwd, path)
                    read_files[pid].add(fullpath)
                    fdpath_map[(pid, screc.exit)] = fullpath
                else:
                    if (pid, fd) in fdpath_map:
                        fullpath = os.path.join(fdpath_map[(pid, fd)], path)
                        read_files[pid].add(fullpath)
                        fdpath_map[(pid, screc.exit)] = fullpath
                    else:
                        print('fd {} for process {} not found'.format(fd,
                            screc.pid), file=sys.stderr)
            
        # non-at* syscalls only
        elif (syscall == 'chmod' or
                syscall == 'chown' or
                syscall == 'lchown' or
                syscall == 'truncate' or
                syscall == 'mkdir' or
                syscall == 'rmdir' or
                syscall == 'unlink' or
                syscall == 'rename' or
                syscall == 'link'):
            try:
                cwd, path, _, filetype = _single_path_parse(parser)
            except TypeError:
                if syscall != 'mkdir':
                    print(syscall)
                    raise
            read_files[pid].add(os.path.join(cwd, path))

        # at syscalls
        elif (syscall == 'mkdirat' or
                syscall == 'unlinkat' or
                syscall == 'renameat' or
                syscall == 'linkat'):
            try:
                cwd, path, _, filetype = _single_path_parse(parser)
            except TypeError:
                if syscall != 'mkdirat':
                    raise
            fd = tofd(screc.a0)
            # the constants below denote AT_FDCWD
            if fd == 'AT_FDCWD':
                read_files[pid].add(os.path.join(cwd, path))
            else:
                if (pid, fd) in fdpath_map:
                    read_files[pid].add(
                            os.path.join(fdpath_map[(pid, fd)], path))
                else:
                    print('fd {} for process {} not found'.format(fd,
                        screc.pid), file=sys.stderr)
        
        if not parser.parse_next_event() or not parser.search_next_event():
            break

def make_system_parser():
    return AuParser(auparse.AUSOURCE_LOGS, None)

def main():
    parser = AuParser(auparse.AUSOURCE_LOGS, None)
    parser.search_add_expression(
            r'(\record_type == "SYSCALL") && (success r= "yes")',
            auparse.AUSEARCH_RULE_CLEAR
            )
    parser.search_set_stop(auparse.AUSEARCH_STOP_EVENT)
    i = 0
    while i < 25 and parser.search_next_event():
        parser.find_field('syscall')
        syscall = parser.interpret_field()
        print(syscall)
        for rec in range(parser.get_num_records()):
            print(parser.get_record_text())
            rec += 1
            parser.goto_record_num(rec)
        print('--------')
        i += 1

if __name__ == '__main__':
    parser = AuParser(auparse.AUSOURCE_FILE, '/tmp/all.log')
    cppauparse(parser)
    print(childparent_map)
    print(fdpath_map)
    print(read_files)
