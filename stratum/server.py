#!/usr/bin/env python3
"""Generate FixedCoin stratum from the known-good FreeCash stratum base."""
import ast, os, runpy, sys, urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent; FULL=HERE/"server_full.py"
URL="https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/a88d89675b3a41cc6774e1b975e57e050d4892cc/stratum/server.py"
ADAPT_VERSION="fixedcoin-fch-dashboard-repair-2026-08-14-v8"

def replace_function(source,name,replacement):
    tree=ast.parse(source); target=next((n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name),None)
    if target is None: raise RuntimeError(f"function {name!r} not found in FreeCash base")
    lines=source.splitlines(keepends=True); start=sum(map(len,lines[:target.lineno-1])); end=sum(map(len,lines[:target.end_lineno])); return source[:start]+replacement.rstrip()+"\n"+source[end:]

def adapt(t):
    t=t.replace('job_interval", 20)','job_interval", 30)').replace('blog[-20:]','blog[-1000:]').replace('+ 14400','+ 100').replace(' FCH',' FIX').replace('FreeCash','FixedCoin').replace('/FCH-Solo/','/FIX-Solo/')
    # FixedCoin Core requires BIP145/SegWit GBT negotiation.
    for old in ('rpc("getblocktemplate", [{"rules": []}]) or rpc("getblocktemplate", [])','rpc("getblocktemplate", [{"rules": []}])'):
        if old in t:
            t=t.replace(old,'rpc("getblocktemplate", [{"rules": ["segwit"]}])',1); break
    if 'rpc("getblocktemplate", [{"rules": ["segwit"]}])' not in t: raise RuntimeError('segwit GBT patch failed')
    marker='MAX_DIFF = int(cfg["pool"].get("vardiff_max", 50_000_000))'
    if marker not in t: raise RuntimeError('vardiff marker missing')
    t=t.replace(marker,marker+'\nFIXED_DIFF = int(cfg["pool"].get("fixed_difficulty", 13354))',1)
    fixed_parser='''def parse_fixed_diff(*candidates):
    for raw in candidates:
        if not raw or not isinstance(raw,str): continue
        m=re.search(r"(?:^|[;,\\s])(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)",raw,re.I)
        if not m: m=re.match(r"^(?:d|diff)\\s*[=:]\\s*(\\d+(?:\\.\\d+)?)$",raw.strip(),re.I)
        if m:
            try:return FIXED_DIFF
            except Exception:pass
    return None
'''
    t=replace_function(t,'parse_fixed_diff',fixed_parser)
    coinbase='''def build_coinbase_parts(height, miner_value_sats, miner_spk, dev_spk=None, en1_size=4, en2_size=4, witness_commitment_hex=None, *args, **kwargs):
    tag=b"/FIX-Solo/"; height_script=bip34_height(height); scriptsig_len=len(height_script)+en1_size+en2_size+len(tag)
    part1=struct.pack("<I",2)+b"\\x01"+b"\\x00"*32+struct.pack("<I",0xFFFFFFFF)+encode_varint(scriptsig_len)+height_script
    witness=b""
    if witness_commitment_hex:
        try:witness=binascii.unhexlify(witness_commitment_hex)
        except Exception:witness=b""
    outputs=2 if witness else 1; part2=tag+struct.pack("<I",0xFFFFFFFF)+encode_varint(outputs)+struct.pack("<Q",int(miner_value_sats))+encode_varint(len(miner_spk))+miner_spk
    if witness:part2+=struct.pack("<Q",0)+encode_varint(len(witness))+witness
    part2+=struct.pack("<I",0); return binascii.hexlify(part1).decode(),binascii.hexlify(part2).decode()
'''
    t=replace_function(t,'build_coinbase_parts',coinbase)
    old='"other_tx": other_tx, "created": time.time(),'
    if old in t:t=t.replace(old,old+'\n                "witness_commitment": tmpl.get("default_witness_commitment"),',1)
    oldcall='''build_coinbase_parts(
            job["height"], job["value"], job["spk"], job["dev_spk"],
            len(self.en1), self.en2_size,
        )'''
    newcall='''build_coinbase_parts(
            job["height"], job["value"], job["spk"], job.get("dev_spk"),
            len(self.en1), self.en2_size, job.get("witness_commitment"),
        )'''
    if oldcall in t:t=t.replace(oldcall,newcall,1)
    t=t.replace('build_coinbase_parts(job["height"], job["value"], job["spk"], job["dev_spk"]','build_coinbase_parts(job["height"], job["value"], job.get("spk"), job.get("dev_spk")',1)
    witness='''def coinbase_add_witness(tx_nowitness,enabled):
    if not enabled or len(tx_nowitness)<8 or tx_nowitness[4:6]==b"\\x00\\x01": return tx_nowitness
    return tx_nowitness[:4]+b"\\x00\\x01"+tx_nowitness[4:-4]+b"\\x01\\x20"+(b"\\x00"*32)+tx_nowitness[-4:]
'''
    if 'def coinbase_add_witness' in t:t=replace_function(t,'coinbase_add_witness',witness)
    else:t=t.replace('\ndef assemble_coinbase(', '\n'+witness+'\ndef assemble_coinbase(',1)
    oldblock='block = header + encode_varint(tx_count) + coinbase_tx'; newblock='block = header + encode_varint(tx_count) + coinbase_add_witness(coinbase_tx, bool(job.get("witness_commitment")))'
    if oldblock in t:t=t.replace(oldblock,newblock,1)
    # Remove noisy getaddressinfo fallback: validateaddress is sufficient for our Bech32 payout.
    oldaddr='''    info2 = rpc("getaddressinfo", [addr])
    if info2 and info2.get("scriptPubKey"):
        return binascii.unhexlify(info2["scriptPubKey"])
'''
    t=t.replace(oldaddr,'')
    # Persist the exact reward/maturity metadata at block acceptance.
    t=t.replace('"mature_at_height": job["height"] + 14400,','"mature_at_height": job["height"] + 100,',1)
    return t

def generate_server():
    print("Fetching known-good FreeCash stratum base…",flush=True); raw=urllib.request.urlopen(URL,timeout=60).read().decode(); adapted=adapt(raw); ast.parse(adapted)
    assert 'rpc("getblocktemplate", [{"rules": ["segwit"]}])' in adapted
    assert 'rpc("getblocktemplate", [{"rules": []}])' not in adapted
    assert 'getaddressinfo' not in adapted or 'getaddressinfo' not in adapted[adapted.find('def address_to_scriptpubkey'):adapted.find('def bip34_height')]
    FULL.write_text(f"# ADAPT_VERSION={ADAPT_VERSION}\n"+adapted); print("Wrote",FULL,FULL.stat().st_size,flush=True)
if os.environ.get('STRATUM_BUILD_ONLY')=='1':generate_server(); raise SystemExit(0)
if not FULL.exists() or ADAPT_VERSION not in FULL.read_text(errors='ignore'):generate_server()
sys.argv[0]=str(FULL); runpy.run_path(str(FULL),run_name='__main__')
