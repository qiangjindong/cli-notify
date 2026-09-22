from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge
from bridge import CompletionState as State


class GoalTests(unittest.TestCase):
    def test_goal_states(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'CODEX_HOME': home}):
            path = Path(home)/'goals_1.sqlite'
            payload = {'session_id': 'main'}
            self.assertEqual(bridge.goal_state(payload), State.READY)
            self.assertFalse(path.exists())
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE thread_goals (thread_id TEXT PRIMARY KEY, status TEXT)')
                db.commit()
                self.assertEqual(bridge.goal_state(payload), State.READY)
                for status in ('active', 'paused', 'blocked', 'usage_limited', 'budget_limited', 'unknown', 'complete'):
                    db.execute('INSERT OR REPLACE INTO thread_goals VALUES (?, ?)', ('main', status))
                    db.commit()
                    expected = State.READY if status == 'complete' else State.STOP
                    self.assertEqual(bridge.goal_state(payload), expected)
                    self.assertEqual(bridge.goal_state({'thread-id': 'main'}), expected)
                    self.assertEqual(bridge.goal_state({'session_id': 'other'}), State.READY)
                db.execute('DROP TABLE thread_goals')
                db.commit()
                with patch('bridge.log'):
                    self.assertEqual(bridge.goal_state(payload), State.RETRY)

    def test_turn_lifecycle(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'CODEX_HOME': home}), patch('bridge.log'):
            rollout = Path(home)/'rollout.jsonl'
            with closing(sqlite3.connect(Path(home)/'state_5.sqlite')) as db, db:
                db.execute('CREATE TABLE threads (id TEXT, rollout_path TEXT)')
                db.execute('INSERT INTO threads VALUES (?, ?)', ('main', str(rollout)))
            payload = {'session_id': 'main', 'turn_id': 'turn'}
            self.assertEqual(bridge.turn_state(payload), State.RETRY)
            def event(kind, turn='turn'):
                return json.dumps({'type': 'event_msg', 'payload': {'type': kind, 'turn_id': turn}}) + '\n'
            for text, expected in [
                ('', State.RETRY),
                (event('task_complete', 'previous'), State.RETRY),
                (event('task_started'), State.RETRY),
                (event('task_complete'), State.READY),
                (event('task_complete') + event('task_started', 'next'), State.STOP),
                (event('task_started') + event('task_started', 'next'), State.STOP),
                (event('task_complete') + event('task_complete', 'next'), State.STOP),
                (event('task_complete') + event('task_started'), State.STOP),
                (event('task_started') + event('turn_aborted'), State.STOP),
                (event('task_complete') + '{partial', State.RETRY),
                (event('task_complete') + event('task_started', None), State.RETRY),
                ('x' * 300000 + '\n' + event('task_complete'), State.READY),
            ]:
                with self.subTest(text=text[:100]):
                    rollout.write_text(text, encoding='utf8')
                    self.assertEqual(bridge.turn_state(payload), expected)
            self.assertEqual(bridge.turn_state({'session_id': 'main'}), State.STOP)

    def test_polling_first_success_stop_and_exhaustion(self):
        for states, expected in [
            ([State.READY], True),
            ([State.RETRY, State.READY], True),
            ([State.RETRY, State.RETRY, State.READY], True),
            ([State.STOP], False),
            ([State.RETRY, State.STOP], False),
            ([State.RETRY] * 3, False),
        ]:
            with self.subTest(states=states), patch('bridge.time.sleep') as sleep, patch('bridge.completion_state', side_effect=states) as check:
                self.assertEqual(bridge.completion_ready({}), expected)
                self.assertEqual(sleep.call_args_list, [call(1)] * len(states))
                self.assertEqual(check.call_count, len(states))

    def test_combines_signals_stop_wins_over_retry(self):
        for goal in State:
            for turn in State:
                expected = (State.STOP if State.STOP in (goal, turn) else
                            State.READY if goal == turn == State.READY else State.RETRY)
                with self.subTest(goal=goal, turn=turn), patch('bridge.goal_state', return_value=goal), patch('bridge.turn_state', return_value=turn):
                    self.assertEqual(bridge.completion_state({}), expected)

    def test_read_failure_recovers_on_next_attempt(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'CODEX_HOME': home}), patch('bridge.log'):
            rollout = Path(home)/'rollout.jsonl'
            with closing(sqlite3.connect(Path(home)/'state_5.sqlite')) as db, db:
                db.execute('CREATE TABLE threads (id TEXT, rollout_path TEXT)')
                db.execute('INSERT INTO threads VALUES (?, ?)', ('main', str(rollout)))
            waits = []
            def sleep(seconds):
                waits.append(seconds)
                if len(waits) == 2:
                    rollout.write_text(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn'}}) + '\n')
            with patch('bridge.time.sleep', side_effect=sleep):
                self.assertTrue(bridge.completion_ready({'session_id': 'main', 'turn_id': 'turn'}))
            self.assertEqual(waits, [1, 1])

    def test_other_native_events_never_poll(self):
        for kind in ('register', 'question', 'approval', 'compact'):
            with self.subTest(kind=kind), patch('bridge.completion_ready') as ready, patch('bridge.time.sleep') as sleep, patch.object(sys, 'argv', ['bridge.py', 'native-worker', kind, '{"session_id":"main"}']), patch('pathlib.Path.read_text', return_value='{"helper":"test"}'), patch.dict(os.environ, {}), patch('bridge.user_thread_name', return_value='name'), patch('bridge.send', return_value=True):
                bridge.main()
                ready.assert_not_called()
                sleep.assert_not_called()

    def test_legacy_success_and_timeout_preserve_original_payload(self):
        raw = json.dumps({'type': 'agent-turn-complete', 'thread-id': 'main', 'turn-id': 'turn'})
        for states in ([State.RETRY, State.READY], [State.RETRY] * 3):
            with self.subTest(states=states), patch('bridge.time.sleep'), patch('bridge.completion_state', side_effect=states), patch.object(sys, 'argv', ['bridge.py', 'complete', raw]), patch.dict(os.environ, {'CWN_ORIGINAL_NOTIFY': '["original"]'}), patch('bridge.user_thread_name', return_value='name'), patch('bridge.send') as send, patch('bridge.log'), patch('bridge.subprocess.Popen') as original:
                bridge.main()
                self.assertEqual(send.call_count, int(states[-1] == State.READY))
                original.assert_called_once_with(['original', raw], stdin=bridge.subprocess.DEVNULL)

    @patch('bridge.time.sleep')
    def test_suppressed_completion_still_chains_original(self, sleep):
        raw = json.dumps({'type': 'agent-turn-complete', 'thread-id': 'main'})
        with patch.object(sys, 'argv', ['bridge.py', 'complete', raw]), patch.dict(os.environ, {'CWN_ORIGINAL_NOTIFY': '["original"]'}), patch('bridge.user_thread_name', return_value='name'), patch('bridge.goal_state', return_value=State.STOP), patch('bridge.send') as send, patch('bridge.log'), patch('bridge.subprocess.Popen') as original:
            bridge.main()
            send.assert_not_called()
            sleep.assert_called_once_with(1)
            self.assertEqual(original.call_args.args[0], ['original', raw])

    @patch('bridge.time.sleep')
    def test_native_suppresses_intermediate_turn(self, sleep):
        payload = json.dumps({'session_id': 'main'})
        with patch.object(sys, 'argv', ['bridge.py', 'native-worker', 'complete', payload]), patch('pathlib.Path.read_text', return_value='{"helper":"test"}'), patch.dict(os.environ, {}), patch('bridge.user_thread_name', return_value='name'), patch('bridge.goal_state', return_value=State.STOP), patch('bridge.send') as send, patch('bridge.log'):
            bridge.main()
            send.assert_not_called()
            sleep.assert_called_once_with(1)
