"""Copy existing evidence without moving/deleting source records or rewriting IDs."""
from pathlib import Path
import sqlite3
import shutil
import json
from datetime import datetime,timezone

def migrate(projects: Path, destination: Path):
    destination.mkdir(parents=True,exist_ok=True)
    marker=destination/'migration.json'
    if marker.exists():
        return json.loads(marker.read_text(encoding='utf-8'))
    evidence=projects/'systematic swing trading bot/backtester/data'
    regime=projects/'Regime-Aware-Systematic-Equities-Trading-Platform/outputs/experiments'
    result={'created_at':datetime.now(timezone.utc).isoformat(),'sources':[str(evidence),str(regime)],'evidence_artifacts':0,'regime_runs':0,'copied_files':0}
    source_db=evidence/'registry.sqlite'
    target_db=destination/'evidence/registry.sqlite'
    if source_db.exists():
        target_db.parent.mkdir(parents=True,exist_ok=True)
        if target_db.exists():raise RuntimeError('Destination registry already exists without a migration marker. Preserve it and resolve migration explicitly.')
        # SQLite backup API includes committed WAL content; no raw live database copy.
        with sqlite3.connect(source_db.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target_db) as dst:
            src.backup(dst)
            result['evidence_artifacts']=dst.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0]
            assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    if evidence.exists():
        for file in evidence.rglob('*'):
            if file.is_file() and not file.name.startswith('registry.sqlite'):
                target=destination/'evidence'/file.relative_to(evidence)
                if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target);result['copied_files']+=1
    if regime.exists():
        for folder in regime.iterdir():
            if not folder.is_dir():continue
            target=destination/'experiments'/folder.name
            if target.exists():raise RuntimeError('Existing experiment destination: '+str(target))
            shutil.copytree(folder,target)
            result['regime_runs']+=1
    marker.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--projects',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(migrate(args.projects,args.destination)))
