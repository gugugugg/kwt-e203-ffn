"""Recheck frozen integer vectors, count input clipping and seal measured provenance."""

import hashlib
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.kwt_fixed import FixedKWT  # noqa: E402
from sim.fixed_ops import encode  # noqa: E402


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    model = FixedKWT(ROOT / 'models/kwt1_fixed16_v1', backend='int64')
    package_hash = (model.directory / 'manifest.sha256').read_text().strip()
    reports = {}
    for name in ['parameter-conversion', 'validation_full-encoder', 'validation-ffn', 'classification']:
        report = json.loads((ROOT / 'reports/numerical' / (name + '.json')).read_text())
        if report['status'] != 'passed':
            raise ValueError('Incomplete or failed local gate: ' + name)
        expected = report.get('parameter_manifest_sha256', report.get('manifest_sha256'))
        if expected != package_hash:
            raise ValueError('Mixed numerical configurations in reports.')
        reports[name] = report
    backend_traces, ffn_checks = 0, 0
    for path in sorted((ROOT / 'data/numerical/fixed16_v1/rtl_vectors').glob('*.npz')):
        with np.load(path) as stored:
            output, trace = model.encoder(stored['encoder_input'], encoded=True, trace=True)
            for key, value in trace.items():
                if not np.array_equal(value, stored[key]):
                    raise ValueError('Fresh int64 trace differs: ' + path.name + '/' + key)
            if not np.array_equal(output, stored['encoder_output']):
                raise ValueError('Encoded output mismatch.')
            backend_traces += 1
    for path in sorted((ROOT / 'data/numerical/fixed16_v1/ffn_vectors').glob('*.npz')):
        with np.load(path) as stored:
            for layer in range(12):
                # These fixtures were produced under the original Python3.8/NumPy1.19
                # runtime; recheck in development Python3.10/NumPy1.23 using scalar-int64 GEMM.
                result = model.ffn(stored[f'layer_{layer:02d}_input_float32'], layer)
                if not np.array_equal(result, stored[f'layer_{layer:02d}_output_codes']):
                    raise ValueError('Cross-runtime FFN vector mismatch.')
                ffn_checks += 1
    if backend_traces != 24 or ffn_checks != 288:
        raise ValueError('Missing complete 24-sample/twelve-layer local fixtures.')
    inputs = np.load(ROOT / 'data/reference/validation_full/encoder_input.npy', mmap_mode='r')
    input_stats = {}
    for i in range(0, len(inputs), 100):
        encode(inputs[i:i+100], model.config['encoder_input_f'], input_stats, 'encoder_input')
    test_suite = ET.parse(ROOT / 'reports/numerical/tests.xml').getroot()
    tests = sum(int(suite.attrib['tests']) for suite in test_suite.iter('testsuite'))
    failed = sum(int(suite.attrib.get('failures', '0')) + int(suite.attrib.get('errors', '0'))
                 for suite in test_suite.iter('testsuite'))
    if failed or tests < 11:
        raise ValueError('Unit/interface checks have not passed.')
    source_paths = [ROOT / 'sim' / name for name in ['fixed_ops.py', 'kwt_fixed.py', 'kwt_reference.py']]
    source_paths += [ROOT / 'scripts' / name for name in ['convert_parameters.py', 'run_numerical.py',
                     'evaluate_numerical.py', 'evaluate_ffn.py', 'score_numerical.py',
                     'export_ffn_tasks.py', 'verify_numerical_artifacts.py', 'Build-Numerical.ps1']]
    source_paths += [ROOT / 'constraints/competition_contract.json', ROOT / 'tests/test_fixed_numerical.py']
    arrays = list((ROOT / 'data/numerical/fixed16_v1').rglob('*.npy'))
    vectors = list((ROOT / 'data/numerical/fixed16_v1').rglob('*.npz'))
    checksums = {path.relative_to(ROOT).as_posix(): {'sha256': digest(path), 'bytes': path.stat().st_size}
                 for path in source_paths + arrays + vectors}
    result = {'status': 'passed', 'package_manifest_sha256': package_hash,
              'entry_group': 'undergraduate', 'optional_scope': 'full twelve-layer encoder',
              'fresh_int64_encoder_trace_checks': backend_traces,
              'cross_runtime_int64_ffn_task_checks': ffn_checks, 'tests_passed': tests,
              'input_encoding_audit': input_stats, 'all_frozen_files': checksums,
              'python': platform.python_version(), 'numpy': np.__version__,
              'undergraduate_max_layer_nrmse': reports['validation-ffn']['max_layer_nrmse'],
              'undergraduate_max_single_task_nrmse': max(reports['validation-ffn']['max_single_task_nrmse_per_layer']),
              'encoder_top1_accuracy': reports['classification']['top1_accuracy'],
              'encoder_top1_drop_percentage_points': reports['classification']['top1_drop_percentage_points'],
              'test_data_used': False, 'quantization_tuned_on_validation': False,
              'rtl_bit_exact_gate': 'pending actual RTL', 'official_600_gate': 'pending official evaluation',
              'soc_timing_area_power_gates': 'pending platform integration and technology data'}
    (ROOT / 'reports/numerical/frozen-run.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['status', 'tests_passed', 'fresh_int64_encoder_trace_checks',
                                                 'cross_runtime_int64_ffn_task_checks', 'undergraduate_max_layer_nrmse',
                                                 'encoder_top1_drop_percentage_points']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
