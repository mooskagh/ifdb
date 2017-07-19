package main

import (
	"errors"
	"syscall"
	"unsafe"
)

import (
	"github.com/lxn/walk"
	"github.com/lxn/win"
)

type LogView struct {
	walk.WidgetBase
}

func NewLogView(parent walk.Container) (*LogView, error) {
	lv := &LogView{}

	if err := walk.InitWidget(
		lv,
		parent,
		"EDIT",
		win.WS_TABSTOP|win.WS_VISIBLE|win.WS_VSCROLL|win.ES_MULTILINE|win.ES_WANTRETURN,
		win.WS_EX_CLIENTEDGE); err != nil {
		return nil, err
	}
	lv.setReadOnly(true)
	lv.SendMessage(win.EM_SETLIMITTEXT, 4294967295, 0)
	return lv, nil
}

func (*LogView) LayoutFlags() walk.LayoutFlags {
	return walk.ShrinkableHorz | walk.ShrinkableVert | walk.GrowableHorz | walk.GrowableVert | walk.GreedyHorz | walk.GreedyVert
}

func (lv *LogView) setTextSelection(start, end int) {
	lv.SendMessage(win.EM_SETSEL, uintptr(start), uintptr(end))
}

func (lv *LogView) textLength() int {
	return int(lv.SendMessage(0x000E, uintptr(0), uintptr(0)))
}

func (lv *LogView) AppendText(value string) {
	textLength := lv.textLength()
	lv.setTextSelection(textLength, textLength)
	lv.SendMessage(win.EM_REPLACESEL, 0, uintptr(unsafe.Pointer(syscall.StringToUTF16Ptr(value+"\n"))))
}

func (lv *LogView) setReadOnly(readOnly bool) error {
	if 0 == lv.SendMessage(win.EM_SETREADONLY, uintptr(win.BoolToBOOL(readOnly)), 0) {
		return errors.New("fail to call EM_SETREADONLY")
	}

	return nil
}
