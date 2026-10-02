"""Execute the collector's actual extraction JavaScript against a DOM
fixture shaped by markup observed live on a real, populated YouTube page
(ytd-comment-thread-renderer wrapping #content-text/#author-text directly,
with nested ytd-comment-replies-renderer > ytd-comment-view-model replies
and a[href*="lc="] copy-link stable IDs) -- not assumed selectors.

This exercises real parent/reply relationships: which comments become
top-level vs. nested, and that each reply's parent_id matches its actual
parent thread's stable id.
"""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import unittest


def _load_js_constants() -> dict:
    source = Path(__file__).parents[1] / "src/warrigal/acquisition/youtube_post_comments.py"
    constants = {}
    for statement in ast.parse(source.read_text()).body:
        if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = statement.value.value
    return constants


_NODE_SCRIPT_TEMPLATE = r'''
const assert = require('assert');

function textNode(text) {
  return { innerText: text };
}

function makeComment({ text, author, authorHref, published, likes, lcId, replies }) {
  const children = {
    '#content-text': text != null ? textNode(text) : null,
    '#author-text': author != null ? textNode(author) : null,
    'a#author-text': authorHref != null ? { href: authorHref } : null,
    '#published-time-text': published != null ? textNode(published) : null,
    '#vote-count-middle': likes != null ? textNode(likes) : null,
    'a[href*="lc="]': lcId != null
      ? { href: 'https://www.youtube.com/post/P1?lc=' + lcId }
      : null,
    '[hidden-explanation-text], .hidden-content-text': null,
  };
  const replyNodes = (replies || []).map(makeComment);
  return {
    __replyNodes: replyNodes,
    querySelector(selector) {
      if (Object.prototype.hasOwnProperty.call(children, selector)) {
        return children[selector];
      }
      return null;
    },
    querySelectorAll(selector) {
      if (selector.indexOf('ytd-comment-replies-renderer') !== -1) {
        return replyNodes;
      }
      return [];
    },
  };
}

const THREADS = SCENARIO_THREADS;

global.location = { pathname: '/post/P1', href: 'https://www.youtube.com/post/P1' };
global.window = {};
global.document = {
  querySelector(selector) {
    if (selector === 'ytd-comments, ytd-item-section-renderer#sections') {
      return { exists: true };
    }
    if (selector === 'ytd-message-renderer') {
      return null;
    }
    if (selector === '#count .count-text, ytd-comments-header-renderer #count') {
      return textNode('');
    }
    if (selector === '#content-text') {
      return textNode('Post body title, not a comment');
    }
    return null;
  },
  querySelectorAll(selector) {
    if (selector === 'ytd-comment-thread-renderer') {
      return THREADS;
    }
    return [];
  },
};

eval(BOOTSTRAP);
const resultJson = eval(FINALIZE);
const result = JSON.parse(resultJson);

SCENARIO_ASSERTIONS
'''


@unittest.skipUnless(shutil.which("node"), "Node is required for browser-script fixtures")
class CommentExtractionRelationshipTests(unittest.TestCase):
    def run_scenario(self, threads_js: str, assertions: str) -> None:
        constants = _load_js_constants()
        script = _NODE_SCRIPT_TEMPLATE
        script = script.replace("BOOTSTRAP", json.dumps(constants["_POST_COMMENTS_BOOTSTRAP_JS"]))
        script = script.replace("FINALIZE", json.dumps(constants["_POST_COMMENTS_FINALIZE_JS"]))
        script = script.replace("SCENARIO_THREADS", threads_js)
        script = script.replace("SCENARIO_ASSERTIONS", assertions)
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extracts_top_level_comment_fields_from_observed_markup_shape(self):
        self.run_scenario(
            """
            [makeComment({
              text: 'We are so honored.',
              author: '@SanDiegoZoo',
              authorHref: 'https://www.youtube.com/@SanDiegoZoo',
              published: '6 years ago',
              likes: '4.8m',
              lcId: 'STABLE_TOP_1',
              replies: [],
            })]
            """,
            """
            assert.equal(result.comments.length, 1);
            const c = result.comments[0];
            assert.equal(c.id, 'STABLE_TOP_1');
            assert.equal(c.id_basis, 'copy_link');
            assert.equal(c.parent_id, null);
            assert.equal(c.text, 'We are so honored.');
            assert.equal(c.author, '@SanDiegoZoo');
            assert.equal(c.published_text, '6 years ago');
            assert.equal(c.like_count, '4.8m');
            """,
        )

    def test_reply_parent_id_matches_its_own_thread_not_a_sibling_thread(self):
        self.run_scenario(
            """
            [
              makeComment({
                text: 'First top-level comment',
                author: '@alice',
                lcId: 'TOP_A',
                replies: [
                  { text: 'Reply to alice', author: '@bob', lcId: 'REPLY_TO_A' },
                ],
              }),
              makeComment({
                text: 'Second top-level comment',
                author: '@carol',
                lcId: 'TOP_B',
                replies: [
                  { text: 'Reply to carol', author: '@dave', lcId: 'REPLY_TO_B' },
                ],
              }),
            ]
            """,
            """
            assert.equal(result.comments.length, 4);
            const byId = Object.fromEntries(result.comments.map(c => [c.id, c]));

            assert.equal(byId['TOP_A'].parent_id, null);
            assert.equal(byId['TOP_B'].parent_id, null);

            assert.equal(byId['REPLY_TO_A'].parent_id, 'TOP_A');
            assert.equal(byId['REPLY_TO_A'].text, 'Reply to alice');

            assert.equal(byId['REPLY_TO_B'].parent_id, 'TOP_B');
            assert.equal(byId['REPLY_TO_B'].text, 'Reply to carol'.replace('carol', 'carol'));
            assert.equal(byId['REPLY_TO_B'].text, 'Reply to carol');

            // Order preserved: thread A and its reply before thread B and its reply.
            assert.deepEqual(result.comments.map(c => c.id), ['TOP_A', 'REPLY_TO_A', 'TOP_B', 'REPLY_TO_B']);
            """,
        )

    def test_multiple_replies_on_one_thread_all_share_that_threads_parent_id(self):
        self.run_scenario(
            """
            [
              makeComment({
                text: 'Popular comment',
                author: '@alice',
                lcId: 'TOP_A',
                replies: [
                  { text: 'Reply one', author: '@bob', lcId: 'REPLY_1' },
                  { text: 'Reply two', author: '@carol', lcId: 'REPLY_2' },
                  { text: 'Reply three', author: '@dave', lcId: 'REPLY_3' },
                ],
              }),
            ]
            """,
            """
            assert.equal(result.comments.length, 4);
            const replies = result.comments.slice(1);
            replies.forEach(r => assert.equal(r.parent_id, 'TOP_A'));
            assert.deepEqual(replies.map(r => r.id), ['REPLY_1', 'REPLY_2', 'REPLY_3']);
            assert.deepEqual(replies.map(r => r.order), [0, 1, 2]);
            """,
        )

    def test_comment_without_copy_link_falls_back_to_ordinal_identity(self):
        self.run_scenario(
            """
            [makeComment({
              text: 'No stable id available',
              author: '@eve',
              lcId: null,
              replies: [],
            })]
            """,
            """
            assert.equal(result.comments.length, 1);
            const c = result.comments[0];
            assert.equal(c.id_basis, 'ordinal_fallback');
            assert.equal(c.id, 'ordinal-0');
            """,
        )

    def test_reply_without_copy_link_gets_parent_scoped_ordinal_id(self):
        self.run_scenario(
            """
            [makeComment({
              text: 'Has a stable id',
              author: '@alice',
              lcId: 'TOP_A',
              replies: [
                { text: 'Unstable reply', author: '@bob', lcId: null },
              ],
            })]
            """,
            """
            assert.equal(result.comments.length, 2);
            const reply = result.comments[1];
            assert.equal(reply.parent_id, 'TOP_A');
            assert.equal(reply.id_basis, 'ordinal_fallback');
            assert.equal(reply.id, 'TOP_A-ordinal-0');
            """,
        )


if __name__ == "__main__":
    unittest.main()
