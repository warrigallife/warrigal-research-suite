"""Execute the collector JavaScript against asynchronous DOM fixtures."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required for browser-script fixtures')
class ReplyBrowserProgressTests(unittest.TestCase):
    def run_fixture(self, scenario):
        source = Path(__file__).parents[1] / 'src/warrigal/acquisition/youtube_post_comments.py'
        constants = {}
        for statement in ast.parse(source.read_text()).body:
            if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = statement.value.value
        script = r'''
const assert = require('assert');
global.window = {};
let replies = 0, active = true, clicks = 0;
const button = {disabled:false, getClientRects:()=>active ? [1] : [],
 closest:()=>null, click:()=>{clicks++;}};
global.document = {
 querySelectorAll: selector => selector.includes('#more-replies') ? [button]
   : selector === 'ytd-comment-thread-renderer' ? [1]
   : Array(replies).fill(1),
 documentElement: {scrollHeight:100}
};
window.scrollTo = ()=>{};
eval(BOOTSTRAP);
window.__wrgWallClockBudgetMs = 60000;
const advance = ()=>eval(ADVANCE);
SCENARIO
'''
        script = script.replace('BOOTSTRAP', json.dumps(constants['_POST_COMMENTS_BOOTSTRAP_JS']))
        script = script.replace('ADVANCE', json.dumps(constants['_POST_COMMENTS_ADVANCE_JS']))
        script = script.replace('SCENARIO', scenario)
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_delayed_reply_progress_resets_failed_click_count(self):
        self.run_fixture("""
assert.equal(advance(), 'CONTINUE');
assert.equal(advance(), 'CONTINUE');
assert.equal(window.__wrgNonProductiveClicks, 1);
replies = 2; // response arrives between polling rounds
assert.equal(advance(), 'CONTINUE');
assert.equal(window.__wrgNonProductiveClicks, 0);
replies = 4;
assert.equal(advance(), 'CONTINUE');
assert.equal(window.__wrgNonProductiveClicks, 0);
""")

    def test_hidden_reply_control_does_not_get_clicked(self):
        self.run_fixture("""
active = false;
assert.equal(advance(), 'CONTINUE');
assert.equal(advance(), 'CONTINUE');
assert.equal(advance(), 'CONTINUE');
assert.equal(advance(), 'DONE');
assert.equal(clicks, 0);
assert.equal(window.__wrgReplyButtons().length, 0);
""")

    def test_visible_nonproductive_reply_control_stops_honestly(self):
        self.run_fixture("""
assert.equal(advance(), 'CONTINUE');
assert.equal(advance(), 'CONTINUE');
assert.equal(advance(), 'CONTINUE');
assert.equal(advance(), 'DONE');
assert.equal(window.__wrgReplyButtons().length, 1);
""")
