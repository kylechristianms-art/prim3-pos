from app.services.receipt_printer import print_receipt, print_kitchen

def print_receipt_service(data, port):
    return print_receipt(data, port)

def print_kitchen_service(data, port):
    return print_kitchen(data, port)