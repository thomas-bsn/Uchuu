def print_user_id_to_check(user_id_to_check):
    # obtenir la longueur maximale du nom d'utilisateur et de l'ID
    max_name_length = max([len(name) for name in user_id_to_check.keys()])
    max_id_length = max([len(str(user_id)) for user_id in user_id_to_check.values()])

    # imprimer le cadre supérieur
    print("+" + "-" * (max_name_length + 2) + "+" + "-" * (max_id_length + 2) + "+")

    # imprimer le titre
    print(f"|{'TARGET':^{max_name_length + max_id_length + 5}}|")

    # imprimer le cadre intermédiaire
    print("+" + "-" * (max_name_length + 2) + "+" + "-" * (max_id_length + 2) + "+")

    # imprimer les noms d'utilisateur et les ID
    for name, user_id in user_id_to_check.items():
        print(f"| {name:<{max_name_length}} | {user_id:<{max_id_length}} |")

    # imprimer le cadre inférieur
    print("+" + "-" * (max_name_length + 2) + "+" + "-" * (max_id_length + 2) + "+")


def load_user_id_to_check(file_path):
    user_id_to_check = {}
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line.startswith('#'):
                name, user_id = line.split(':')
                user_id_to_check[name] = int(user_id)
    # print_user_id_to_check(user_id_to_check)
    return user_id_to_check