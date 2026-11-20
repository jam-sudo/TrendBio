import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml


def test_workflow_reconciles_earlier_forks_then_restores_latest_snapshot(tmp_path):
    workflow = yaml.safe_load(Path('.github/workflows/field-pilot.yml').read_text())
    step = next(s['run'] for s in workflow['jobs']['pilot']['steps']
                if s.get('name') == "Restore the field's editorial decisions")
    gh = """
    gh() {
      if [[ "$1 $2" == "api --paginate" ]]; then cat pages.json
      elif [[ "$1" == api ]]; then echo '{"event":"workflow_dispatch","path":".github/workflows/field-pilot.yml"}'
      else
        [[ "$1 $2" == "run download" ]]
        mkdir -p "$7"
        cp -R "archives/$3/." "$7/"
      fi
    }
    """
    entries = []
    for run, artifact in [(11, 900), (12, 100), (13, 500)]:
        folder = tmp_path / 'archives' / str(run) / 'classifications'
        folder.mkdir(parents=True)
        (folder / 'shared.json').write_text(str(run))
        (folder / f'{run}.json').write_text(str(run))
        entries.append({'id': artifact, 'created_at': f'2026-11-20T00:{run}:00Z', 'expired': False,
                        'workflow_run': {'head_branch': 'main', 'head_repository_id': 5, 'id': run}})

    def restore(run):
        (tmp_path / 'pages.json').write_text(json.dumps([{'artifacts': entries}]))
        subprocess.run(['bash', '-ec', gh + step], cwd=tmp_path, check=True, env={
            **os.environ, 'DOMAIN': 'computer-information', 'GITHUB_REPOSITORY_ID': '5', 'GITHUB_RUN_ID': str(run),
            'GITHUB_REPOSITORY': 'owner/repo', 'RUNNER_TEMP': str(tmp_path / str(run)),
            'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary'),
        })
        target = tmp_path / 'science-pilot/computer-information/decisions'
        assert (target / 'classifications/shared.json').read_text() == '11'
        assert all((target / f'classifications/{n}.json').is_file() for n in (11, 12, 13))
        return target, json.loads((target / 'lineage.json').read_text())['restored_newest_first']

    merged, origins = restore(14)
    assert origins == ['13', '12', '11']
    shutil.move(merged, tmp_path / 'archives/14')
    entries.append({**entries[-1], 'id': 1, 'created_at': '2026-11-20T00:14:00Z',
                    'workflow_run': {**entries[-1]['workflow_run'], 'id': 14}})
    _, origins = restore(15)
    assert origins == ['14']
