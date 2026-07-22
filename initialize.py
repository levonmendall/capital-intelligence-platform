from core.seed import seed_mandates

if __name__ == "__main__":
    created = seed_mandates()
    print(f"Initialization complete. New mandates created: {created}")
