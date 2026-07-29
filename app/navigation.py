from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ViewState:
    screen: str
    page: int = 0
    payload: str | None = None


@dataclass(slots=True)
class NavigationHistory:
    current: ViewState = field(default_factory=lambda: ViewState("home"))
    _back_stack: list[ViewState] = field(default_factory=list)
    max_depth: int = 20

    def open(
        self,
        screen: str,
        *,
        page: int = 0,
        payload: str | None = None,
        remember: bool = True,
    ) -> ViewState:
        next_view = ViewState(screen=screen, page=max(page, 0), payload=payload)
        if remember and next_view != self.current:
            self._back_stack.append(self.current)
            if len(self._back_stack) > self.max_depth:
                del self._back_stack[0]
        self.current = next_view
        return next_view

    def refresh(self) -> ViewState:
        return self.current

    def back(self) -> ViewState:
        if self._back_stack:
            self.current = self._back_stack.pop()
        else:
            self.current = ViewState("home")
        return self.current

    def reset(self) -> ViewState:
        self._back_stack.clear()
        self.current = ViewState("home")
        return self.current
