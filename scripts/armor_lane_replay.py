"""Replay the TNO0049 configurations, keeping source and build artifacts in this checkout."""
import argparse
from pathlib import Path
import resource
import shutil

from cv32e40p_compare import ROOT, CXX, identity, run, save
from cv32e40p_repair_compare import emit_environment, native_library
from grhsim_single_baseline import clean_environment
from xiangshan_cv32_ablation_measure import read, verify
from xiangshan_packed_storage_compare import check_model, source_shape, source_inventory


def prepare(archive, out, tools):
    out.mkdir(parents=True, exist_ok=False)
    ref = archive/'build/xs/indexed-snapshot-default-20261117-v1'
    xs = archive/'build/xs/indexed-snapshot-20261117-v3/candidate'
    cv = archive/'build/cv32e40p/indexed-snapshot-v3'
    old = read(ref/'report.json')
    for record in old['models'].values():
        verify(record)
    check_model(xs)
    verify(read(cv/'build.json')['binaries']['grhsim_indexed_snapshot'])
    inputs = read(ref/'logs/xs-default.command.json')['argv']
    graph = Path(inputs[1])
    if identity(graph) != read(xs/'configuration.json')['shared_input']:
        raise ValueError('XS input mismatch')
    cvgraph = Path(read(ref/'logs/cv32-default.command.json')['argv'][1])
    frozen_cv = read(cv/'build.json')['frozen_inputs']
    verify(next(record for record in frozen_cv if record['path'] == str(cvgraph)))
    native = out/'native'
    native.mkdir()
    shutil.copy2(native_library(tools), native/'libwolvrix-lib.so')
    shutil.copy2(tools/'cv32e40p_emit', native/'cv32e40p_emit')
    command = read(ref/'logs/xs-native.command.json')['argv']
    source = ROOT/'scripts/xiangshan_cv32_emit.cpp'
    new = [s.replace(str(ref/'native/include'), str(ROOT/'wolvrix/include'))
           .replace(str(ref/'snapshot/xiangshan_cv32_emit.cpp'), str(source))
           .replace(str(ref/'native'), str(native)) for s in command]
    run(new, out/'xs-native.log')
    save(out/'inputs.json', dict(xs=identity(graph), cv=identity(cvgraph), compiler=identity(CXX),
        native=[identity(p) for p in native.iterdir()], xs_binary=read(xs/'binary.json'),
        cv_binary=read(cv/'build.json')['binaries']['grhsim_indexed_snapshot'],
        emit_source=identity(ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp'),
        planner=identity(ROOT/'wolvrix/lib/emit/grhsim_bool_lane_pack.hpp'),
        archive=str(archive), current=str(ROOT)))


def emit_frozen_model(out, design, target, switches):
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    cfg = read(out/'inputs.json')
    archive = Path(cfg['archive'])
    for record in cfg['native']:
        verify(record)
    native = out/'native'
    env = clean_environment()
    if design == 'xs':
        env.update(LD_LIBRARY_PATH=str(native), LC_ALL='C', NOOP_HOME=str(archive/'testcase/xiangshan'),
            WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0', WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0',
            WOLVRIX_GRHSIM_CONDITIONAL_MUX_SHARED_ARM='1')
        args = [native/'emit',cfg['xs']['path'],target]
        baseline = archive/'build/xs/indexed-snapshot-20261117-v3/candidate/model'
    else:
        env = emit_environment(native)
        env.update(CV32_EVENT_REGIONS_SHARED='1', CV32_SHARED_EVENT_REGIONS_CONNECTED='1',
            WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1', WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',
            WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1', WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',
            WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1', WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1',
            WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0', WOLVRIX_GRHSIM_CONDITIONAL_MUX_SHARED_ARM='1')
        args = [native/'cv32e40p_emit',cfg['cv']['path'],target,'off']
        baseline = archive/'build/cv32e40p/indexed-snapshot-v3/grhsim_indexed_snapshot'
    env.update(switches)
    run(args, target.parent/'emit.log', env=env)
    actual, previous = source_inventory(target), source_inventory(baseline)
    unchanged = source_shape(actual) == source_shape(previous)
    if design == 'cv' and identity(target/'normalized.json')['sha256'] != identity(baseline/'normalized.json')['sha256']:
        raise ValueError('CV32 normalized graph changed')
    save(target.parent/'sources.json',dict(unchanged=unchanged,count=len(actual),files=actual))
    return unchanged


def generate(out, design, candidate=False):
    target = out/(design if candidate else design+'-off')/'model'
    same = emit_frozen_model(out, design, target, {
        'WOLVRIX_GRHSIM_BOOL_LANE_PACK_AUDIT': '1',
        'WOLVRIX_GRHSIM_BOOL_LANE_PACK': str(int(candidate))})
    if not candidate and not same:
        raise ValueError(design+': off source drift')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','xs','cv'))
    p.add_argument('--archive',type=Path,default=ROOT.parent/'wolvrix-playground-cv32e40p')
    p.add_argument('--tools',type=Path,default=ROOT/'build/armor-lane-v1/tools')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--candidate',action='store_true')
    a=p.parse_args()
    if a.stage=='prepare': prepare(a.archive.resolve(),a.output.resolve(),a.tools.resolve())
    else: generate(a.output.resolve(),a.stage,a.candidate)
