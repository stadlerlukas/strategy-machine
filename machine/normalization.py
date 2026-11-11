import csv
from pathlib import Path
from .common import require,file_hash,write_json,now
from .data import validate_rows,save_csv


def normalize_csv(source,mapping,target):
    require(mapping.get("price_adjustment")=="unadjusted","Confirm that source prices are unadjusted; do not double-apply corporate actions")
    require(mapping.get("currency"),"Record the valuation currency")
    rows=[]
    with Path(source).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        for raw in reader:
            row={}
            for field in ("date","symbol","open","close","status","split","dividend","settlement"):
                column=mapping.get("columns",{}).get(field)
                if column:
                    require(column in raw,f"Missing source column: {column}")
                    value=raw[column]
                else:
                    require(field in mapping.get("constants",{}),f"Explicit column or constant required for {field}")
                    value=mapping["constants"][field]
                if field in ("open","close","split","dividend"):
                    value=float(value)
                if field=="settlement":
                    value=float(value) if value not in (None,"") else None
                row[field]=value
            for name,column in mapping.get("features",{}).items():
                require(column in raw,f"Missing feature column {column}")
                row["feature_"+name]=float(raw[column]) if raw[column]!="" else None
            rows.append(row)
    rows.sort(key=lambda r:(r["date"],r["symbol"]))
    validate_rows(rows,sorted({r["symbol"] for r in rows}))
    target=Path(target)
    require(not target.exists(),"Normalized destination exists; preserve versions with a new filename")
    target.parent.mkdir(parents=True,exist_ok=True)
    save_csv(target,rows)
    manifest={"source":str(Path(source).resolve()),"source_sha256":file_hash(source),"output_sha256":file_hash(target),"mapping":mapping,"created_at":now(),"rows":len(rows)}
    write_json(str(target)+".provenance.json",manifest)
    return manifest
