from memory_store import get_unconfirmed_incidents, update_incident_outcome

def main():
    incidents = get_unconfirmed_incidents()

    if not incidents:
        print("No unconfirmed incidents. Nothing to review.")
        return

    print(f"Found {len(incidents)} unconfirmed incident(s):\n")

    for inc in incidents:
        print("=" * 60)
        print(f"ID: {inc['id']} | Repo: {inc['repo']} | Category: {inc['category']}")
        print(f"Error: {inc['error_message']}")
        print(f"Suggested fix: {inc['fix_text'][:200]}...")
        print()

        answer = input("Did this fix work? (y/n/skip): ").strip().lower()
        if answer == "y":
            update_incident_outcome(inc["id"], True)
        elif answer == "n":
            update_incident_outcome(inc["id"], False)
        else:
            print("Skipped.\n")
            continue
        print()

if __name__ == "__main__":
    main()