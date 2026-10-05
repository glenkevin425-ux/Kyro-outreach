import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import server as kyro


class FakeProvider:
    def __init__(self, fail=False):
        self.fail = fail
        self.lock = threading.Lock()
        self.calls = 0

    def send_email(self, **kwargs):
        with self.lock:
            self.calls += 1
        if self.fail:
            raise RuntimeError("simulated provider rejection")
        return {"id": "fake-message-" + str(self.calls), "status": "accepted"}


class QuotaSafeguardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = kyro.DB_PATH
        self.old_provider = kyro.make_provider
        kyro.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        kyro.init_db()
        self.uid = "test-workspace"
        with kyro.db_connect() as c:
            c.execute("INSERT INTO users(id,workspace_id,email,password_hash,display_name,is_demo,created_at) VALUES(?,?,?,?,?,?,?)",
                      (self.uid, self.uid, "owner@example.com", kyro.password_hash("a sufficiently long test password"), "Glen", 0, kyro.iso_now()))
            kyro.create_profile_and_settings(c, self.uid, "Glen", "Glen", "glen@kcreatives.example")
            c.execute("UPDATE profiles SET timezone='UTC' WHERE user_id=?", (self.uid,))
            c.execute("UPDATE agency_settings SET sending_window_start='00:00',sending_window_end='23:59',daily_limit=10 WHERE user_id=?", (self.uid,))
            self.cid = "campaign-test"
            c.execute("INSERT INTO campaigns(id,user_id,name,service_focus,status,daily_limit,sending_window_start,sending_window_end,follow_up_delay_days,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (self.cid, self.uid, "Safety test", "Branding", "Active", 10, "00:00", "23:59", 4, kyro.iso_now(), kyro.iso_now()))
        self.provider = FakeProvider()
        kyro.make_provider = lambda: self.provider
        with kyro.db_connect() as c:
            self.user = c.execute("SELECT * FROM users WHERE id=?", (self.uid,)).fetchone()

    def tearDown(self):
        kyro.make_provider = self.old_provider
        kyro.DB_PATH = self.old_path
        self.tmp.cleanup()

    def add_approved_draft(self, number):
        pid = f"prospect-{number}"
        did = f"draft-{number}"
        email = f"contact{number}@example.com"
        now = kyro.iso_now()
        with kyro.db_connect() as c:
            c.execute("INSERT INTO prospects(id,user_id,business_name,contact_name,email,status,tags,created_at,updated_at) VALUES(?,?,?,?,?,'New','[]',?,?)",
                      (pid, self.uid, f"Business {number}", "Contact", email, now, now))
            c.execute("INSERT INTO campaign_prospects(user_id,campaign_id,prospect_id,status,created_at) VALUES(?,?,?,'Selected',?)",
                      (self.uid, self.cid, pid, now))
            c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,personalization_notes,service_focus,status,kind,approved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (did, self.uid, pid, self.cid, f"A quick note for Business {number}",
                       "Hi Contact,\n\nA factual test message.\n\nBest,\nGlen", "", "Branding", "Approved", "initial", now, now, now))
        return did

    def count_today(self):
        with kyro.db_connect() as c:
            timezone = c.execute("SELECT timezone FROM profiles WHERE user_id=?", (self.uid,)).fetchone()["timezone"]
            date = kyro.local_now(timezone).date().isoformat()
            row = c.execute("SELECT count FROM daily_send_counters WHERE user_id=? AND date=? AND timezone=?",
                            (self.uid, date, timezone)).fetchone()
            return row["count"] if row else 0

    def test_concurrent_sends_never_exceed_ten(self):
        ids = [self.add_approved_draft(i) for i in range(12)]

        def attempt(draft_id):
            try:
                return kyro.send_draft(self.user, draft_id, f"outreach:{draft_id}")
            except kyro.APIError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(attempt, ids))
        paired = list(zip(ids, results))
        successes = [(draft_id, result) for draft_id, result in paired if isinstance(result, dict) and result.get("sent")]
        blocked = [draft_id for draft_id, result in paired if result == "quota_reached"]
        self.assertEqual(len(successes), 10)
        self.assertEqual(len(blocked), 2)
        self.assertEqual(self.count_today(), 10)
        # A repeated idempotent request returns the existing result and does not call the provider again.
        calls = self.provider.calls
        sent_draft_id = successes[0][0]
        again = kyro.send_draft(self.user, sent_draft_id, f"outreach:{sent_draft_id}")
        self.assertTrue(again["duplicate"])
        self.assertEqual(self.count_today(), 10)
        self.assertEqual(self.provider.calls, calls)
        with self.assertRaises(kyro.APIError) as raised:
            kyro.send_draft(self.user, blocked[0], f"outreach:{blocked[0]}")
        self.assertEqual(raised.exception.code, "quota_reached")
        self.assertEqual(self.count_today(), 10)
        # Changing the workspace timezone cannot reset the same calendar day's quota.
        with kyro.db_connect() as c:
            c.execute("UPDATE profiles SET timezone='Asia/Tokyo' WHERE user_id=?", (self.uid,))
        with self.assertRaises(kyro.APIError) as raised_after_tz_change:
            kyro.send_draft(self.user, blocked[0], f"outreach:{blocked[0]}")
        self.assertEqual(raised_after_tz_change.exception.code, "quota_reached")
        with kyro.db_connect() as c:
            self.assertEqual(kyro.successful_sends_today(c, self.uid, "Asia/Tokyo"), 10)

    def test_provider_failure_does_not_consume_quota(self):
        draft_id = self.add_approved_draft("fail")
        self.provider.fail = True
        with self.assertRaises(kyro.APIError) as raised:
            kyro.send_draft(self.user, draft_id, f"outreach:{draft_id}")
        self.assertEqual(raised.exception.code, "provider_rejected")
        self.assertEqual(self.count_today(), 0)
        with kyro.db_connect() as c:
            failed = c.execute("SELECT COUNT(*) AS n FROM email_sends WHERE user_id=? AND draft_id=? AND status='failed'", (self.uid, draft_id)).fetchone()["n"]
            reservation = c.execute("SELECT status FROM send_reservations WHERE user_id=? AND draft_id=?", (self.uid, draft_id)).fetchone()["status"]
        self.assertEqual(failed, 1)
        self.assertEqual(reservation, "released")

    def test_duplicate_draft_send_is_idempotent(self):
        draft_id = self.add_approved_draft("idem")
        first = kyro.send_draft(self.user, draft_id, f"outreach:{draft_id}")
        second = kyro.send_draft(self.user, draft_id, f"outreach:{draft_id}")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.count_today(), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_suppression_blocks_send_before_provider(self):
        draft_id = self.add_approved_draft("suppressed")
        with kyro.db_connect() as c:
            prospect = c.execute("SELECT id,email FROM prospects WHERE id='prospect-suppressed'").fetchone()
            c.execute("INSERT INTO suppressions(id,user_id,email,reason,created_at) VALUES(?,?,?,?,?)",
                      ("suppression-test", self.uid, prospect["email"], "Do not contact", kyro.iso_now()))
        with self.assertRaises(kyro.APIError) as raised:
            kyro.send_draft(self.user, draft_id, f"outreach:{draft_id}")
        self.assertEqual(raised.exception.code, "suppressed")
        self.assertEqual(self.count_today(), 0)
        self.assertEqual(self.provider.calls, 0)

    def test_reply_stops_pending_followups(self):
        draft_id = self.add_approved_draft("reply")
        result = kyro.send_draft(self.user, draft_id, f"outreach:{draft_id}")
        with kyro.db_connect() as c:
            fup = c.execute("SELECT * FROM follow_ups WHERE user_id=? AND prospect_id='prospect-reply'", (self.uid,)).fetchone()
            self.assertIsNotNone(fup)
            kyro.stop_pending_outreach(c, self.uid, "prospect-reply")
            c.execute("UPDATE prospects SET status='Replied',responded_at=?,updated_at=? WHERE id='prospect-reply'", (kyro.iso_now(), kyro.iso_now()))
            fup_status = c.execute("SELECT status FROM follow_ups WHERE id=?", (fup["id"],)).fetchone()["status"]
            follow_draft_status = c.execute("SELECT status FROM email_drafts WHERE id=?", (fup["draft_id"],)).fetchone()["status"]
        self.assertEqual(result["sent"], True)
        self.assertEqual(fup_status, "cancelled")
        self.assertEqual(follow_draft_status, "Cancelled")

    def test_demo_send_is_only_a_simulation(self):
        demo_id = "demo-test-workspace"
        with kyro.db_connect() as c:
            c.execute("INSERT INTO users(id,workspace_id,email,password_hash,display_name,is_demo,created_at) VALUES(?,?,?,?,?,?,?)",
                      (demo_id, demo_id, "demo-test@example.invalid", kyro.password_hash("unused test password"), "Demo", 1, kyro.iso_now()))
            kyro.create_profile_and_settings(c, demo_id, "Demo", "Demo", "demo@kcreatives.example")
            c.execute("UPDATE profiles SET timezone='UTC' WHERE user_id=?", (demo_id,))
            c.execute("UPDATE agency_settings SET sending_window_start='00:00',sending_window_end='23:59' WHERE user_id=?", (demo_id,))
            c.execute("INSERT INTO campaigns(id,user_id,name,service_focus,status,daily_limit,sending_window_start,sending_window_end,follow_up_delay_days,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      ("demo-campaign", demo_id, "Demo campaign", "Branding", "Active", 10, "00:00", "23:59", 4, kyro.iso_now(), kyro.iso_now()))
            c.execute("INSERT INTO prospects(id,user_id,business_name,contact_name,email,status,tags,created_at,updated_at) VALUES(?,?,?,?,?,'New','[]',?,?)",
                      ("demo-prospect", demo_id, "Fictional business", "Demo contact", "contact@fictional.example", kyro.iso_now(), kyro.iso_now()))
            c.execute("INSERT INTO campaign_prospects(user_id,campaign_id,prospect_id,status,created_at) VALUES(?,?,?,'Selected',?)",
                      (demo_id, "demo-campaign", "demo-prospect", kyro.iso_now()))
            c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,service_focus,status,kind,approved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      ("demo-draft", demo_id, "demo-prospect", "demo-campaign", "A demo subject", "A demo email body.", "Branding", "Approved", "initial", kyro.iso_now(), kyro.iso_now(), kyro.iso_now()))
            demo_user = c.execute("SELECT * FROM users WHERE id=?", (demo_id,)).fetchone()
        result = kyro.send_draft(demo_user, "demo-draft", "demo-send:key-0001")
        self.assertTrue(result["sent"])
        self.assertIn("not delivered", result["provider_status"].lower())
        self.assertEqual(self.provider.calls, 0)
        with kyro.db_connect() as c:
            demo_count = c.execute("SELECT count FROM daily_send_counters WHERE user_id=?", (demo_id,)).fetchone()["count"]
        self.assertEqual(demo_count, 1)


if __name__ == "__main__":
    unittest.main()
