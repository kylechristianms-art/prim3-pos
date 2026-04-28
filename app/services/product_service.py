from database import Product

def get_low_stock():
    products = Product.query.filter(Product.quantity <= 5).all()

    return [
        {"id": p.id, "name": p.name, "quantity": p.quantity}
        for p in products
    ]