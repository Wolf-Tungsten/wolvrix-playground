#!/usr/bin/env python3
"""Verify that the new default reproduces frozen measured model sources; no simulation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import platform
import resource
import shutil

from cv32e40p_compare import ROOT, identity, run, save
from cv32e40p_event_regions_compare import check as cv_check
from cv32e40p_repair_compare import GRAPH, emit_environment, native_library
from grhsim_single_baseline import clean_environment
from indexed_snapshot_compare import read, OPTION
from xiangshan_cv32_compare import HISTORICAL, XS, verify_identity
from xiangshan_packed_storage_compare import source_inventory, source_shape, check_model

XS_MEASURED=ROOT/'build/xs/indexed-snapshot-20261117-v3'
CV_MEASURED=ROOT/'build/cv32e40p/indexed-snapshot-v3'


def prepare(out, tools):
    assert platform.node().startswith('node030')
    out.mkdir(parents=True,exist_ok=False);native=out/'native';snap=out/'snapshot';native.mkdir();snap.mkdir()
    for src in (tools/'cv32e40p_emit',native_library(tools)):shutil.copy2(src,native/src.name)
    shutil.copytree(ROOT/'wolvrix/include',native/'include')
    for src in (ROOT/'scripts/xiangshan_cv32_emit.cpp',ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',
                ROOT/'wolvrix/tests/emit/test_emit_grhsim_cpp.cpp',Path(__file__).resolve()):shutil.copy2(src,snap/src.name)
    previous=(CV_MEASURED/'source-snapshot/grhsim_cpp.cpp').read_text()
    current=(snap/'grhsim_cpp.cpp').read_text()
    before='"WOLVRIX_GRHSIM_INDEXED_CONCAT_SNAPSHOT_ARRAY", false);'
    after='"WOLVRIX_GRHSIM_INDEXED_CONCAT_SNAPSHOT_ARRAY", true);'
    assert previous.count(before)==current.count(after)==1
    assert previous.replace(before,after)==current,'production changes beyond default promotion'
    files=[p for d in (native,snap) for p in sorted(d.rglob('*')) if p.is_file()]
    save(out/'inputs.json',[identity(p) for p in files])
    save(out/'policy.json',dict(change='Only indexed_concat_snapshot_array default false -> true',
        generation_inputs='Default: option absent from environment and attributes. Explicit off also checked on CV32.',
        source_comparison='Exact bytes for every model C++ file, header and Makefile against TNO0049 frozen candidates.',
        simulation=False,performance=False,feedback=False))


def check_inputs(out):
    for record in read(out/'inputs.json'):verify_identity(record)


def compare(actual, expected):
    current,old=source_inventory(actual),source_inventory(expected)
    assert source_shape(current)==source_shape(old),'generated source differs: '+str(actual)
    return dict(status='pass',files=len(current),generated=current,measured=old)


def cv(out):
    check_inputs(out);cv_check(CV_MEASURED);native=out/'native';env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',CV32_SHARED_EVENT_REGIONS_CONNECTED='1',
        WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1',
        WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0',WOLVRIX_GRHSIM_CONDITIONAL_MUX_SHARED_ARM='1')
    env.pop(OPTION,None);results={}
    for mode,expected in (('default',CV_MEASURED/'grhsim_indexed_snapshot'),('off',CV_MEASURED/'grhsim_shared_arm')):
        local=env.copy()
        if mode=='off':local[OPTION]='0'
        assert (OPTION not in local) if mode=='default' else local[OPTION]=='0'
        target=out/'cv32'/mode
        run([native/'cv32e40p_emit',GRAPH,target,'off'],out/'logs'/('cv32-'+mode+'.log'),env=local)
        assert identity(target/'normalized.json')['sha256']==identity(expected/'normalized.json')['sha256']
        results[mode]=compare(target,expected)
    save(out/'cv32.json',dict(status='pass',models=results,policy=identity(out/'policy.json')))
    print('CV32 default matches measured on; explicit off matches measured control',flush=True)


def xs(out):
    check_inputs(out);check_model(XS_MEASURED/'candidate')
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    native=out/'native';env=clean_environment();env.update(NOOP_HOME=str(XS),LC_ALL='C',LD_LIBRARY_PATH=str(native),
        WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0',WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_SHARED_ARM='1')
    assert OPTION not in env
    command=[arg.replace(str(XS_MEASURED/'native'),str(native)).replace(str(XS_MEASURED/'snapshot'),str(out/'snapshot'))
             for arg in read(XS_MEASURED/'logs/native.command.json')['argv']]
    command[-1]=str(native/'emit')
    run(command,out/'logs/xs-native.log',env=env)
    run([native/'emit',HISTORICAL/'pre_reg_to_mem.json',out/'xs-default'],out/'logs/xs-default.log',env=env)
    result=compare(out/'xs-default',XS_MEASURED/'candidate/model')
    save(out/'xs.json',dict(**result,policy=identity(out/'policy.json'),binary=read(XS_MEASURED/'candidate/binary.json')))
    print('XS default matches measured on',flush=True)


def verify(out):
    assert platform.node().startswith('node030')
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(f,out) for f in (cv,xs)]
        for job in jobs:job.result()
    check_inputs(out)
    save(out/'report.json',dict(status='pass',production_change='one option default',models={n:identity(out/(n+'.json')) for n in ('cv32','xs')},
        inputs=identity(out/'inputs.json'),policy=identity(out/'policy.json'),
        note='Generated sources are byte-identical to frozen tested candidates; no new simulation or timing samples.'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('prepare','verify'));p.add_argument('--output',required=True,type=Path)
    p.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools');a=p.parse_args();out=a.output.resolve()
    if a.stage=='prepare':prepare(out,a.tools.resolve())
    else:verify(out)
