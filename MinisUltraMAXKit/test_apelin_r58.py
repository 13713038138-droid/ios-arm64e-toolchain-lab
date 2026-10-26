import importlib.util,json,os,subprocess,tempfile
from pathlib import Path
import unittest
src=Path(__file__).with_name("apelin_bridge_r58.py")
sp=importlib.util.spec_from_file_location("apelin_bridge_r58",src)
b=importlib.util.module_from_spec(sp);sp.loader.exec_module(b)
class Tests(unittest.TestCase):
    def test_only_readonly(self):
        ops=[v["op"] for v in json.loads(b.payload())["steps"]]
        self.assertEqual(ops,["hello","extensionList","sdkList","toolchainStatus"])
    def test_invalid_token(self):
        for token in ("","aaa","abc; rm -rf /"):
            with self.assertRaises(ValueError):b.collect_script(token)
    def test_stage_pending_collect(self):
        with tempfile.TemporaryDirectory() as d:
            token="deadbeefcafebabe";env=dict(os.environ,HOME=d)
            p=subprocess.run(["sh","-c",b.stage_script(token)],input=b.payload(),capture_output=True,env=env)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run(["sh","-c",b.collect_script(token)],capture_output=True,env=env)
            self.assertEqual(p.returncode,3)
            base=Path(d)/"Documents/wiki.qaq.apelin/console"
            (base/"done").mkdir();(base/"out").mkdir()
            run="20261026-000000-abc"
            (base/"done"/(run+"-minis-r58-"+token+".json")).write_text("{}")
            (base/"inbox"/("minis-r58-"+token+".json")).unlink()
            raw='{"type":"run.start"}\n'
            raw+="".join(json.dumps({"type":"step.result","op":op,"ok":True})+"\n" for op in b.OPS)
            raw+='{"type":"run.end","ok":true}\n'
            (base/"out"/(run+".jsonl")).write_text(raw)
            got=subprocess.run(["sh","-c",b.collect_script(token)],capture_output=True,env=env)
            self.assertEqual(got.returncode,0,got.stderr)
            with tempfile.NamedTemporaryFile() as f:
                Path(f.name).write_bytes(got.stdout)
                self.assertTrue(b.summarize(f.name)["passed"])
    def test_not_false_positive(self):
        with tempfile.NamedTemporaryFile() as f:
            Path(f.name).write_text('{"type":"run.end","ok":true}\n')
            self.assertFalse(b.summarize(f.name)["passed"])
if __name__=="__main__":unittest.main()
