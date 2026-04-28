def calculate_change(total, cash_received, method):
    if method.lower() != "cash":
        return 0
    return float(cash_received) - float(total)