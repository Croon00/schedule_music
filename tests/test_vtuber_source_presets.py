from app.core.db import VTUBER_X_SOURCES


def test_requested_vtuber_x_sources_are_seeded() -> None:
    assert VTUBER_X_SOURCES == (
        ("MOCO", "hth_moco"),
        ("BAMBI", "hth_bambi"),
        ("SAKUYA", "NUROJUNK_SAKUYA"),
        ("KAGURA", "NJ_KAGURA"),
        ("Enma_Ruri", "Ruri_Enma"),
        ("Setono_Toto", "setono_toto1010"),
        ("Setono_Toto", "setono_toto_sub"),
        ("Minase_Nagi", "minase_nagi7"),
    )
