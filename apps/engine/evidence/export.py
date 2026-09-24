"""Portable lab export; independent of any dashboard runtime."""
import io
import zipfile
from pathlib import Path
import pandas as pd
from .storage import canonical, digest

def export_bundle(store, report, dataset_kind):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.json',canonical(report))
        dataset=store.get(report['dataset_id'],dataset_kind)
        archive.writestr('dataset.json',canonical(dataset))
        archive.writestr('observations.csv',pd.DataFrame(dataset['rows']).to_csv(index=False))
        for name,expected in report.get('code',{}).get('source_hashes',{}).items():
            path=Path(__file__).parent/Path(name).name
            if path.is_file() and digest(path.read_bytes())==expected:
                archive.writestr('evidence/'+path.name,path.read_bytes())
        archive.writestr('environment.json',canonical(report.get('code',{})))
        archive.writestr('README.txt','Source labels and assumptions apply to all results. Replay with python -m evidence.replay_lab PATH_TO_ZIP using matching code and dependencies. Historical exports may need the retained original environment.')
    return buffer.getvalue()
