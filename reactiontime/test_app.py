import os
import tempfile
import unittest
from pathlib import Path

test_directory = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(test_directory.name) / 'test.db'}"
os.environ["SECRET_KEY"] = "test-only-secret"

from app import app, db, limiter  # noqa: E402


def tearDownModule():
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    test_directory.cleanup()


class AccountAndLeaderboardTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
        limiter.reset()
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()

    def post(self, path, data):
        return self.client.post(
            path,
            json=data,
            headers={"Origin": "http://localhost"},
        )

    def register(self, username="speedy", password="password123"):
        return self.post(
            "/api/register",
            {"username": username, "password": password},
        )

    def test_registration_stores_password_hash_and_logs_user_in(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"]["username"], "speedy")
        self.assertEqual(self.client.get("/api/me").json["user"]["username"], "speedy")

        with app.app_context():
            from app import User

            user = db.session.scalar(db.select(User))
            self.assertNotEqual(user.password_hash, "password123")
            self.assertTrue(user.password_hash.startswith("scrypt:"))

    def test_duplicate_usernames_are_case_insensitive(self):
        self.assertEqual(self.register().status_code, 201)
        response = self.register(username="SPEEDY")
        self.assertEqual(response.status_code, 409)

    def test_login_accepts_username_without_case_sensitivity(self):
        self.register()
        self.client.post(
            "/api/logout",
            json={},
            headers={"Origin": "http://localhost"},
        )

        response = self.post(
            "/api/login",
            {"username": "SPEEDY", "password": "password123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["username"], "speedy")

    def test_rejects_invalid_registration_and_wrong_password(self):
        self.assertEqual(
            self.register(username="x").status_code,
            400,
        )
        self.register()
        response = self.post(
            "/api/login",
            {"username": "speedy", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

    def test_mutations_require_same_origin(self):
        response = self.client.post(
            "/api/register",
            json={"username": "speedy", "password": "password123"},
        )
        self.assertEqual(response.status_code, 403)

    def test_scores_are_saved_and_leaderboard_shows_best_time_per_user(self):
        self.register()
        for reaction_ms in (300, 245, 280):
            response = self.post("/api/scores", {"reaction_ms": reaction_ms})
            self.assertEqual(response.status_code, 201)

        history = self.client.get("/api/scores")
        self.assertCountEqual(
            [score["reaction_ms"] for score in history.json["scores"]],
            [300, 245, 280],
        )
        self.assertEqual(history.json["scores"][0]["reaction_ms"], 280)

        leaderboard = self.client.get("/api/leaderboard")
        self.assertEqual(
            leaderboard.json["scores"],
            [{"username": "speedy", "best_ms": 245}],
        )

    def test_scores_require_login_and_valid_reaction_times(self):
        self.assertEqual(
            self.post("/api/scores", {"reaction_ms": 200}).status_code,
            401,
        )
        self.register()
        for invalid_time in (0, -1, 10_001, True, "200"):
            response = self.post(
                "/api/scores",
                {"reaction_ms": invalid_time},
            )
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
