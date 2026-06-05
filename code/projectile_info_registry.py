from projectile_info_loader import load_external_projectile_info


def build_projectile_info():
    return load_external_projectile_info()


def replace_projectile_info(new_projectile_info):
    PROJECTILE_INFO.clear()
    PROJECTILE_INFO.update(new_projectile_info)


PROJECTILE_INFO = build_projectile_info()