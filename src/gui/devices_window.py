"""Toplevel for managing every configured Tuya bulb: renaming its local display
name (never touches the device itself - the local Tuya protocol has no name field
to write to), and grouping bulbs so the main window can drive several of them at
once. Mutates the shared DevicesConfig object in place and calls on_change after
every edit, so the caller (MainWindow) can persist it and refresh its device/group
selector.
"""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from src import devices_config
from src.device_config import DeviceConfig
from src.devices_config import DeviceGroup, DevicesConfig, device_selection_key, new_group_id
from src.gui.device_config_dialog import DeviceConfigDialog

ROW_PADY = 4


class TextInputDialog(ctk.CTkToplevel):
    """Small modal prompt for a single line of text - used for both renaming a
    device and naming a new group."""

    def __init__(self, master: ctk.CTk, title: str, label: str, on_save: Callable[[str], None],
                 initial: str = ""):
        super().__init__(master)
        self._on_save = on_save

        self.title(title)
        self.geometry("300x160")
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(self, text=label).pack(pady=(20, 4))
        self.entry = ctk.CTkEntry(self, width=240)
        self.entry.insert(0, initial)
        self.entry.pack(pady=(0, 16))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack()
        ctk.CTkButton(button_row, text="Save", command=self._on_save_click).pack(side="left", padx=6)
        ctk.CTkButton(button_row, text="Cancel", fg_color="gray40", command=self.destroy).pack(side="left", padx=6)

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()
        self.entry.focus()
        self.entry.select_range(0, "end")

    def _on_save_click(self) -> None:
        value = self.entry.get().strip()
        if not value:
            self.destroy()
            return
        self._on_save(value)
        self.destroy()


class GroupChoiceDialog(ctk.CTkToplevel):
    """Asks whether a device should join a brand-new group or an existing one -
    shown only once at least one group already exists."""

    def __init__(self, master: ctk.CTk, on_create_new: Callable[[], None],
                 on_add_existing: Callable[[], None]):
        super().__init__(master)

        self.title("Add to group")
        self.geometry("280x150")
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(self, text="Create a new group or add to an existing one?", wraplength=240).pack(
            pady=(20, 12), padx=16
        )
        ctk.CTkButton(self, text="Create new group", command=lambda: self._choose(on_create_new)).pack(
            pady=4, padx=20, fill="x"
        )
        ctk.CTkButton(self, text="Add to existing group", command=lambda: self._choose(on_add_existing)).pack(
            pady=4, padx=20, fill="x"
        )

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()

    def _choose(self, action: Callable[[], None]) -> None:
        self.destroy()
        action()


class GroupPickerDialog(ctk.CTkToplevel):
    """Lists existing groups; picking one adds the device to it."""

    def __init__(self, master: ctk.CTk, groups: list[DeviceGroup], on_pick: Callable[[DeviceGroup], None]):
        super().__init__(master)

        self.title("Select group")
        self.geometry(f"280x{120 + 40 * len(groups)}")
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(self, text="Choose a group").pack(pady=(16, 8))
        for group in groups:
            ctk.CTkButton(self, text=group.name, command=lambda g=group: self._choose(g, on_pick)).pack(
                pady=4, padx=20, fill="x"
            )

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()

    def _choose(self, group: DeviceGroup, on_pick: Callable[[DeviceGroup], None]) -> None:
        self.destroy()
        on_pick(group)


class DevicesWindow(ctk.CTkToplevel):
    """Lists every configured device under "Single devices" (ungrouped) and
    "Grouped devices" (by group), with rename/group/remove controls per device."""

    def __init__(self, master: ctk.CTk, config: DevicesConfig, on_change: Callable[[], None]):
        super().__init__(master)
        self._config = config
        self._on_change = on_change

        self.title("Devices")
        self.geometry("400x480")
        self.transient(master)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="Devices", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Add device", width=110, command=self._on_add_device_click).pack(side="right")

        self.scroll_frame = ctk.CTkScrollableFrame(self, width=360, height=380)
        self.scroll_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.after(50, self._make_modal)
        self._render()

    def _make_modal(self) -> None:
        self.grab_set()

    # -- Mutations ----------------------------------------------------------------

    def _on_add_device_click(self) -> None:
        DeviceConfigDialog(self, on_save=self._on_device_added, existing=None)

    def _on_device_added(self, config: DeviceConfig) -> None:
        if not config.display_name:
            config.display_name = config.device_id
        self._config.devices.append(config)
        if not self._config.active_selection:
            self._config.active_selection = device_selection_key(config.device_id)
        self._changed()

    def _on_change_name_click(self, device: DeviceConfig) -> None:
        TextInputDialog(
            self, title="Change name", label="Display name",
            initial=device.display_name or device.device_id,
            on_save=lambda name: self._rename(device, name),
        )

    def _rename(self, device: DeviceConfig, name: str) -> None:
        device.display_name = name
        self._changed()

    def _on_group_click(self, device: DeviceConfig) -> None:
        if not self._config.groups:
            self._prompt_new_group(device)
        else:
            GroupChoiceDialog(
                self,
                on_create_new=lambda: self._prompt_new_group(device),
                on_add_existing=lambda: self._prompt_existing_group(device),
            )

    def _prompt_new_group(self, device: DeviceConfig) -> None:
        TextInputDialog(
            self, title="New group", label="Group name", on_save=lambda name: self._create_group(device, name)
        )

    def _create_group(self, device: DeviceConfig, name: str) -> None:
        group = DeviceGroup(group_id=new_group_id(), name=name, device_ids=[device.device_id])
        self._config.groups.append(group)
        self._changed()

    def _prompt_existing_group(self, device: DeviceConfig) -> None:
        GroupPickerDialog(self, groups=self._config.groups, on_pick=lambda group: self._add_to_group(device, group))

    def _add_to_group(self, device: DeviceConfig, group: DeviceGroup) -> None:
        if device.device_id not in group.device_ids:
            group.device_ids.append(device.device_id)
        self._changed()

    def _on_remove_from_group(self, device: DeviceConfig, group: DeviceGroup) -> None:
        if device.device_id in group.device_ids:
            group.device_ids.remove(device.device_id)
        group.positions.pop(device.device_id, None)
        if not devices_config.can_merge(group):
            group.merged = False
        if not group.device_ids:
            self._config.groups.remove(group)
        self._changed()

    def _on_position_changed(self, device: DeviceConfig, group: DeviceGroup, choice: str) -> None:
        if choice == "-":
            group.positions.pop(device.device_id, None)
        else:
            group.positions[device.device_id] = choice
        if not devices_config.can_merge(group):
            group.merged = False
        self._changed()

    def _on_merge_click(self, group: DeviceGroup) -> None:
        group.merged = not group.merged
        self._changed()

    def _changed(self) -> None:
        self._on_change()
        self._render()

    # -- Rendering ------------------------------------------------------------------

    def _find_device(self, device_id: str) -> DeviceConfig | None:
        return next((d for d in self._config.devices if d.device_id == device_id), None)

    def _render(self) -> None:
        for child in self.scroll_frame.winfo_children():
            child.destroy()

        grouped_ids = {device_id for group in self._config.groups for device_id in group.device_ids}
        single_devices = [d for d in self._config.devices if d.device_id not in grouped_ids]

        if single_devices:
            ctk.CTkLabel(self.scroll_frame, text="Single devices", font=ctk.CTkFont(weight="bold")).pack(
                anchor="w", pady=(4, 4)
            )
            for device in single_devices:
                self._render_device_row(device, grouped=False)

        if self._config.groups:
            ctk.CTkLabel(self.scroll_frame, text="Grouped devices", font=ctk.CTkFont(weight="bold")).pack(
                anchor="w", pady=(12, 4)
            )
            for group in self._config.groups:
                group_header = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
                group_header.pack(fill="x", pady=(6, 0))
                ctk.CTkLabel(group_header, text=group.name, text_color="gray60").pack(side="left")
                merge_ready = group.merged or devices_config.can_merge(group)
                ctk.CTkButton(
                    group_header, text="Unmerge" if group.merged else "Merge", width=80,
                    state="normal" if merge_ready else "disabled",
                    command=lambda g=group: self._on_merge_click(g),
                ).pack(side="right")
                for device_id in group.device_ids:
                    device = self._find_device(device_id)
                    if device is not None:
                        self._render_device_row(device, grouped=True, group=group)

    def _render_device_row(self, device: DeviceConfig, grouped: bool, group: DeviceGroup | None = None) -> None:
        row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        row.pack(fill="x", pady=ROW_PADY)
        ctk.CTkLabel(row, text=device.display_name or device.device_id, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        if grouped:
            current_position = group.positions.get(device.device_id, "-")
            position_menu = ctk.CTkOptionMenu(
                row, values=["-"] + devices_config.available_positions(group, device.device_id), width=80,
                command=lambda choice, d=device, g=group: self._on_position_changed(d, g, choice),
            )
            position_menu.set(current_position)
            position_menu.pack(side="left", padx=4)
        ctk.CTkButton(row, text="Change name", width=100, command=lambda: self._on_change_name_click(device)).pack(
            side="left", padx=4
        )
        if grouped:
            ctk.CTkButton(
                row, text="Remove", width=70, fg_color="gray40",
                command=lambda: self._on_remove_from_group(device, group),
            ).pack(side="left", padx=4)
        else:
            ctk.CTkButton(row, text="Group", width=70, command=lambda: self._on_group_click(device)).pack(
                side="left", padx=4
            )
