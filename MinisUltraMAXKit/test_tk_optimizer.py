#!/usr/bin/env python3
import importlib.util
from pathlib import Path
from decimal import Decimal
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

base = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("tk", base / "tk_optimizer.py")
tk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk)

class TKTests(unittest.TestCase):
    def test_empty(self): self.assertEqual(tk.estimate(""),0)
    def test_cjk(self): self.assertGreater(tk.estimate("中文输入测试"),0)
    def test_duplicate(self):
        a="long line needs dedup "*8
        self.assertGreater(tk.stats(a+"\n"+a)["estimated_duplicate_line_tokens"],0)
    def test_critical_evidence_retained(self):
        msg="\n".join("harmless %03d very long line"%i for i in range(500))+"\nfatal error: owner lease not retained"
        value,report=tk.pack(msg,900)
        self.assertIn("owner lease not retained",value)
        self.assertFalse(report["refused"])
        self.assertLess(tk.estimate(value),tk.estimate(msg))
    def test_budget_fails_closed(self):
        msg="\n".join("fatal error %s %s"%(i,"x"*100) for i in range(300))
        value,report=tk.pack(msg,400)
        self.assertTrue(report["refused"])
        self.assertIn("fatal error 299",value)
    def test_secret_redaction(self):
        value,_=tk.pack("fatal error token=VERY_SECRET_TOKEN",500)
        self.assertNotIn("VERY_SECRET_TOKEN",value)
    def test_cost_cache_subtracted(self):
        self.assertEqual(tk.cost(1000000,0,200000,"10","20","2"),"8.400000")
    def test_cost_invalid(self):
        with self.assertRaises(ValueError): tk.cost(10,0,20,1,2,3)
    def test_cost_negative(self):
        with self.assertRaises(ValueError): tk.cost(-10,0,0,1,2,3)
    def test_chat_invalid_lines(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/"a.jsonl"
            f.write_text("invalid\n"+json.dumps({"role":"tool","content":"done"})+"\n")
            ans=tk.chat(f)
            self.assertEqual(ans["invalid_jsonl_lines"],[1])
            self.assertIn("tool",ans["estimated_by_role"])
    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/"original.log";f.write_text("hello world")
            with redirect_stderr(StringIO()): result=tk.main(["pack-log",str(f),"--out",str(f)])
            self.assertEqual(result,2)
            self.assertEqual(f.read_text(),"hello world")
    def test_cli_cost(self):
        with redirect_stdout(StringIO()) as o:
            self.assertEqual(tk.main(["cost","--input","1000000","--output","0","--cached","0","--input-rate","3","--output-rate","10","--cached-rate","1"]),0)
        self.assertEqual(json.loads(o.getvalue())["cost_at_user_supplied_rates"],"3.000000")

if __name__=="__main__":
    unittest.main()
