import contextlib,io,json,os,tempfile,unittest
from pathlib import Path
import taskctl
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.old=os.environ.get("MINIS_DEV_ULTRA_STATE");os.environ["MINIS_DEV_ULTRA_STATE"]=self.t.name;self.addCleanup(self.restore)
 def restore(self):
  if self.old is None:os.environ.pop("MINIS_DEV_ULTRA_STATE",None)
  else:os.environ["MINIS_DEV_ULTRA_STATE"]=self.old
 def call(self,args,expect=0):
  o,e=io.StringIO(),io.StringIO()
  with contextlib.redirect_stdout(o),contextlib.redirect_stderr(e):r=taskctl.main(args)
  self.assertEqual(r,expect,e.getvalue());return json.loads(o.getvalue()) if o.getvalue().strip() else None
 def create(self):
  return self.call(["create","--id","task-a","--title","Build","--project","/tmp/project"])
 def test_create_and_list(self):
  self.create();self.assertEqual(self.call(["list"])["count"],1);self.assertEqual(self.call(["show","task-a"])["events"][0]["kind"],"created")
 def test_no_overwrite(self):
  self.create();self.assertEqual(taskctl.main(["create","--id","task-a","--title","other","--project","/tmp"]),2)
  self.assertEqual(self.call(["show","task-a"])["task"]["title"],"Build")
 def test_checkpoint_and_resume(self):
  self.create();self.call(["status","task-a","--value","running"]);self.call(["checkpoint","task-a","--stage","build","--next-step","rerun tests"])
  self.call(["status","task-a","--value","blocked"]);self.assertEqual(self.call(["resume","task-a"])["next_step"],"rerun tests")
 def test_failed_needs_checkpoint(self):
  self.create();self.call(["status","task-a","--value","running"]);self.call(["status","task-a","--value","failed"]);self.assertEqual(taskctl.main(["resume","task-a"]),2)
 def test_invalid_transition(self):
  self.create();self.assertEqual(taskctl.main(["status","task-a","--value","passed"]),2)
 def test_secret_redaction(self):
  self.create();self.call(["event","task-a","--message","github_pat_abcdefghijklmnopqrstuvwxyz0123456789"])
  raw=(Path(self.t.name)/"tasks/task-a/events.jsonl").read_text();self.assertNotIn("github_pat_abcdefghijklmnopqrstuvwxyz0123456789",raw);self.assertIn("[REDACTED]",raw)
 def test_invalid_id_and_symlink(self):
  self.assertEqual(taskctl.main(["show","../escape"]),2);base=Path(self.t.name)/"tasks";base.mkdir();out=Path(self.t.name)/"outside";out.mkdir();(base/"task-link").symlink_to(out,target_is_directory=True);self.assertEqual(taskctl.main(["show","task-link"]),2)
if __name__=="__main__":unittest.main()
