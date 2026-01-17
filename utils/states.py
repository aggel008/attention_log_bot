from aiogram.fsm.state import State, StatesGroup

class PostState(StatesGroup):
    viewing_preview = State()        # Режим просмотра превью
    waiting_for_correction = State() # Режим ожидания ручной правки текста