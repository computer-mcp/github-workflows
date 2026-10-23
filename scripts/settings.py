"""Compare the settings declared in Computer MCP's MAINTENANCE with GET data."""

from github_api import Unavailable


READ_ONLY = {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}
MERGES = {"allow_squash_merge": True, "allow_merge_commit": False,
          "allow_rebase_merge": False, "delete_branch_on_merge": True}
RULES = {"deletion", "non_fast_forward", "required_signatures", "pull_request", "required_status_checks"}


def compare(label, expected, actual):
    result = []
    if not isinstance(actual, dict):
        return [f"UNKNOWN {label}: expected an object response"]
    for key, value in expected.items():
        if key not in actual:
            result.append(f"UNKNOWN {label}.{key}: field unavailable")
        elif type(actual[key]) is not type(value) or actual[key] != value:
            result.append(f"DRIFT {label}.{key}: expected {value!r}; observed {actual[key]!r}")
    return result


def ruleset_findings(repo, ruleset, queue):
    findings = compare(repo + ".ruleset", {"target": "branch", "enforcement": "active", "bypass_actors": []}, ruleset)
    findings += compare(repo + ".ruleset.ref_name", {"include": ["~DEFAULT_BRANCH"], "exclude": []},
                        ruleset.get("conditions", {}).get("ref_name"))
    entries = ruleset.get("rules")
    if not isinstance(entries, list) or any(not isinstance(rule, dict) or "type" not in rule for rule in entries):
        return findings + [f"UNKNOWN {repo}.ruleset: rules unavailable"]
    rules = {rule["type"]: rule.get("parameters", {}) for rule in entries}
    if len(rules) != len(entries):
        findings.append(f"DRIFT {repo}.ruleset: duplicate rule types")
    for missing in sorted(RULES - rules.keys()):
        findings.append(f"DRIFT {repo}.ruleset: missing {missing}")
    if "pull_request" in rules:
        findings += compare(repo + ".ruleset.pull_request", {"allowed_merge_methods": ["squash"]}, rules["pull_request"])
    if "required_status_checks" in rules:
        checks = rules["required_status_checks"].get("required_status_checks")
        if not isinstance(checks, list) or not checks or any(not item.get("context") for item in checks):
            findings.append(f"DRIFT {repo}.ruleset: requires no valid checks")
        if queue:
            findings += compare(repo + ".ruleset.required_status_checks",
                                {"strict_required_status_checks_policy": False}, rules["required_status_checks"])
    if queue:
        if "merge_queue" not in rules:
            findings.append(f"DRIFT {repo}.ruleset: missing merge queue")
        else:
            findings += compare(repo + ".ruleset.merge_queue", {"merge_method": "SQUASH", "grouping_strategy": "ALLGREEN"},
                                rules["merge_queue"])
    return findings


def check(api, organization, declaration, repositories):
    findings = []

    def observe(function):
        try:
            findings.extend(function())
        except (Unavailable, KeyError, TypeError, AttributeError) as error:
            findings.append("UNKNOWN " + (str(error) if isinstance(error, Unavailable) else "incomplete settings response"))

    def names(path, key):
        return sorted(item["name"] for item in api.collection(path, key))

    def credential_findings(root, expected):
        result = []
        for kind in ("secrets", "variables"):
            result += compare(root, {kind: sorted(expected.get(kind, []))}, {kind: names(root + "/actions/" + kind, kind)})
        return result

    credentials = {}
    apps = declaration["apps"]
    for app in apps.values():
        for repo in app["stored"]:
            expected = credentials.setdefault(repo, {"secrets": set(), "variables": set()})
            expected["secrets"].add(declaration["credential_secret"].replace("<credentials>", app["prefix"]))
            expected["variables"].add(declaration["credential_variable"].replace("<credentials>", app["prefix"]))
    root = "orgs/" + organization
    observe(lambda: compare("organization.workflow_token", READ_ONLY, api.get(root + "/actions/permissions/workflow")))
    observe(lambda: credential_findings(root, {}))
    repo_names = {repo["name"] for repo in repositories}
    declared = set(credentials).union(*(app["installed"] for app in apps.values()))
    findings.extend(f"DRIFT {repo}: declared in MAINTENANCE but absent from organization" for repo in sorted(declared - repo_names))

    def repository_findings(repo):
        name = repo["name"]
        root = f"repos/{organization}/{name}"
        detail = api.get(root)
        result = compare(name, MERGES, detail)
        if not repo["fork"]:
            result += compare(name, {"default_branch": declaration["default_branch"]}, detail)
        observe(lambda: compare(name + ".workflow_token", READ_ONLY, api.get(root + "/actions/permissions/workflow")))
        observe(lambda: credential_findings(root, credentials.get(name, {})))
        rulesets = api.collection(root + "/rulesets?includes_parents=true")
        owned = []
        for item in rulesets:
            source = item.get("source")
            if item.get("source_type") == "Repository" and source == f"{organization}/{name}":
                endpoint = root + f"/rulesets/{item['id']}"
            elif item.get("source_type") == "Organization" and source == organization:
                endpoint = f"orgs/{organization}/rulesets/{item['id']}"
            else:
                raise Unavailable(f"{name}: unknown ruleset source")
            ruleset = api.get(endpoint)
            if ruleset["name"] == "default branch" and source == f"{organization}/{name}":
                owned.append(ruleset)
            has_queue = any(rule["type"] == "merge_queue" for rule in ruleset["rules"])
            if has_queue and not (name == declaration["queue_repository"] and ruleset in owned):
                result.append(f"DRIFT {name}: undeclared merge queue in {ruleset['name']}")
        if not repo["private"]:
            if len(owned) != 1:
                result.append(f"DRIFT {name}: expected one owned default branch ruleset; observed {len(owned)}")
            else:
                result += ruleset_findings(name, owned[0], name == declaration["queue_repository"])
        return result

    for repo in repositories:
        observe(lambda repo=repo: repository_findings(repo))

    def app_findings():
        result = []
        installed_list = api.collection(f"orgs/{organization}/installations", "installations")
        installed = {item["app_slug"]: item for item in installed_list}
        if len(installed) != len(installed_list):
            result.append("DRIFT organization: duplicate App installations")
        result.extend(f"DRIFT {slug}: installed but undeclared" for slug in sorted(installed.keys() - apps.keys()))
        for slug, app in apps.items():
            installation = installed.get(slug)
            if installation is None:
                result.append(f"DRIFT {slug}: not installed")
                continue
            permissions = {key: value for key, value in installation["permissions"].items() if key != "metadata"}
            result += compare(slug, {"permissions": app["permissions"], "events": [], "repository_selection": "selected"},
                              {**installation, "permissions": permissions})
            observe(lambda installation=installation, app=app, slug=slug:
                    compare(slug, {"repositories": app["installed"]},
                            {"repositories": names(f"user/installations/{installation['id']}/repositories", "repositories")}))
        return result

    observe(app_findings)
    return findings
