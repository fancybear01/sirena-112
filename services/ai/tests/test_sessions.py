def _request(scenario, elapsed=None):
    payload = {
        "sessionId": "session-test-1",
        "scenario": scenario,
        "submittedCard": {
            "incidentType": scenario["groundTruth"]["incidentType"],
            "address": scenario["groundTruth"]["address"],
            "services": scenario["groundTruth"]["requiredServices"],
            "fields": {"victims": "нет"},
        },
        "transcript": [
            {"role": "OPERATOR", "text": "Служба 112, слушаю вас", "atMs": 0},
            {"role": "CALLER", "text": "Помогите!", "atMs": 1200},
        ],
        "actions": [{"type": "CARD_FIELD_SET", "atMs": 2500, "field": "address"}],
    }
    if elapsed is not None:
        payload["elapsedSeconds"] = elapsed
    return payload


def test_criteria_points_sum_to_max_score(client, scenario):
    body = client.post("/ai/sessions/score", json=_request(scenario)).json()

    total_max = round(sum(item["maxPoints"] for item in body["criteria"]), 2)
    assert total_max == body["maxScore"]


def test_total_score_equals_earned_minus_penalties(client, scenario):
    body = client.post("/ai/sessions/score", json=_request(scenario, elapsed=120)).json()

    earned = sum(item["earnedPoints"] for item in body["criteria"])
    penalties = sum(item["points"] for item in body["penalties"])
    assert body["totalScore"] == round(max(0.0, earned - penalties), 2)


def test_every_lost_point_is_explained(client, scenario):
    body = client.post("/ai/sessions/score", json=_request(scenario)).json()

    failed = [item["code"] for item in body["criteria"] if item["status"] != "PASSED"]
    explained = [item["code"].replace("CRITERION_", "") for item in body["errors"]]
    assert sorted(failed) == sorted(explained)
    assert all(item["message"] for item in body["errors"])


def test_time_penalty_applied_only_over_limit(client, scenario):
    limit = scenario["timeLimitSeconds"]

    within = client.post("/ai/sessions/score", json=_request(scenario, elapsed=limit)).json()
    over = client.post("/ai/sessions/score", json=_request(scenario, elapsed=limit + 1)).json()

    assert within["penalties"] == []
    assert [item["code"] for item in over["penalties"]] == ["TIME_LIMIT_EXCEEDED"]
    assert over["totalScore"] < within["totalScore"]


def test_critical_error_blocks_pass(client, scenario):
    body = client.post("/ai/sessions/score", json=_request(scenario)).json()

    has_critical = any(item["severity"] == "CRITICAL" for item in body["errors"])
    if has_critical:
        assert body["passed"] is False


def test_recommendation_for_each_error(client, scenario):
    body = client.post("/ai/sessions/score", json=_request(scenario)).json()

    assert len(body["recommendations"]) == len(body["errors"])


def test_score_is_reproducible(client, scenario):
    payload = _request(scenario, elapsed=55)

    first = client.post("/ai/sessions/score", json=payload)
    second = client.post("/ai/sessions/score", json=payload)

    assert first.json() == second.json()
