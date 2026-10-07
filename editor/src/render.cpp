#include "render.h"
#include <d3dcompiler.h>
#include <wincodec.h>
#include <cstring>
#include <vector>

template <class T> static void rel(T*& p) { if (p) { p->Release(); p = nullptr; } }

bool Renderer::init(HWND hwnd, int w, int h) {
    DXGI_SWAP_CHAIN_DESC sd = {};
    sd.BufferCount = 2;
    sd.BufferDesc.Width = w; sd.BufferDesc.Height = h;
    sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.OutputWindow = hwnd;
    sd.SampleDesc.Count = 1;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    D3D_FEATURE_LEVEL fl;
    const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_0};
    HRESULT hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, levels, 2, D3D11_SDK_VERSION, &sd, &swap_, &dev_, &fl, &ctx_);
    if (FAILED(hr))   // no GPU driver: fall back to the software rasteriser so the editor still opens
        hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, levels, 2, D3D11_SDK_VERSION, &sd, &swap_, &dev_, &fl, &ctx_);
    if (FAILED(hr)) return false;
    createTargets();

    // fullscreen-triangle vertex shader
    const char* vsSrc =
        "struct VSOut { float4 pos : SV_Position; float2 uv : TEXCOORD0; };\n"
        "VSOut main(uint id : SV_VertexID) { VSOut o; float2 uv = float2((id << 1) & 2, id & 2);\n"
        "  o.uv = uv; o.pos = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1); return o; }\n";
    ID3DBlob *blob = nullptr, *err = nullptr;
    if (FAILED(D3DCompile(vsSrc, strlen(vsSrc), "vs", nullptr, nullptr, "main", "vs_5_0", 0, 0, &blob, &err))) { rel(err); return false; }
    dev_->CreateVertexShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &vs_);
    rel(blob); rel(err);

    D3D11_BUFFER_DESC bd = {};
    bd.ByteWidth = (codegen::kCbufBytes + 15) & ~15;
    bd.Usage = D3D11_USAGE_DEFAULT; bd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    dev_->CreateBuffer(&bd, nullptr, &cb_);

    D3D11_SAMPLER_DESC sm = {};
    sm.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sm.AddressU = sm.AddressV = sm.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    dev_->CreateSamplerState(&sm, &samp_);

    D3D11_TEXTURE2D_DESC td = {};
    td.Width = td.Height = kPreview; td.MipLevels = td.ArraySize = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT; td.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
    dev_->CreateTexture2D(&td, nullptr, &previewTex_);
    dev_->CreateRenderTargetView(previewTex_, nullptr, &previewRtv_);
    dev_->CreateShaderResourceView(previewTex_, nullptr, &previewSrv_);
    td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    for (int i = 0; i < 2; i++) { dev_->CreateTexture2D(&td, nullptr, &imgTex_[i]); dev_->CreateShaderResourceView(imgTex_[i], nullptr, &imgSrv_[i]); }
    useSample(0); useSample(1);
    return true;
}

void Renderer::shutdown() {
    for (int i = 0; i < 2; i++) { rel(imgSrv_[i]); rel(imgTex_[i]); }
    rel(samp_); rel(cb_); rel(ps_); rel(vs_); rel(previewSrv_); rel(previewRtv_); rel(previewTex_);
    releaseTargets(); rel(swap_); rel(ctx_); rel(dev_);
}

void Renderer::createTargets() {
    ID3D11Texture2D* back = nullptr;
    swap_->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&back);
    dev_->CreateRenderTargetView(back, nullptr, &backRtv_);
    rel(back);
}
void Renderer::releaseTargets() { rel(backRtv_); }
void Renderer::resize(int w, int h) {
    if (!swap_ || w <= 0 || h <= 0) return;
    releaseTargets();
    swap_->ResizeBuffers(0, w, h, DXGI_FORMAT_UNKNOWN, 0);
    createTargets();
}
void Renderer::beginFrame(const float clear[4]) {
    ctx_->OMSetRenderTargets(1, &backRtv_, nullptr);
    ctx_->ClearRenderTargetView(backRtv_, clear);
}
void Renderer::present() { swap_->Present(1, 0); }

bool Renderer::compileShader(std::string& error) {
    std::string src = codegen::hlsl();
    ID3DBlob *blob = nullptr, *err = nullptr;
    HRESULT hr = D3DCompile(src.data(), src.size(), "transition.hlsl", nullptr, nullptr, "main", "ps_5_0", 0, 0, &blob, &err);
    if (FAILED(hr)) { error = err ? (const char*)err->GetBufferPointer() : "shader compile failed"; rel(err); return false; }
    rel(ps_);
    hr = dev_->CreatePixelShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &ps_);
    rel(blob); rel(err);
    return SUCCEEDED(hr);
}

void Renderer::renderPreview(const Project& p, const Baked baked[kTracks], double progress) {
    if (!ps_) return;
    codegen::Cbuf cb;
    codegen::fillCbuf(p, baked, progress, 1.0, cb);       // the workspace is square: aspect 1
    ctx_->UpdateSubresource(cb_, 0, nullptr, &cb, 0, 0);
    D3D11_VIEWPORT vp = {0, 0, (float)kPreview, (float)kPreview, 0, 1};
    ctx_->RSSetViewports(1, &vp);
    ctx_->OMSetRenderTargets(1, &previewRtv_, nullptr);
    ctx_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ctx_->IASetInputLayout(nullptr);
    ctx_->VSSetShader(vs_, nullptr, 0);
    ctx_->PSSetShader(ps_, nullptr, 0);
    ctx_->PSSetConstantBuffers(0, 1, &cb_);
    ctx_->PSSetShaderResources(0, 2, imgSrv_);
    ctx_->PSSetSamplers(0, 1, &samp_);
    ctx_->Draw(3, 0);
    ID3D11ShaderResourceView* none[2] = {nullptr, nullptr};
    ctx_->PSSetShaderResources(0, 2, none);
}

void Renderer::setImagePixels(int which, const unsigned char* rgba) {
    ctx_->UpdateSubresource(imgTex_[which], 0, nullptr, rgba, kPreview * 4, 0);
}

// Built-in sample pictures: a coloured gradient with a grid, a ring and a big letter, so motion and rotation are easy to read.
void Renderer::useSample(int which) {
    const int N = kPreview;
    std::vector<unsigned char> px(N * N * 4);
    for (int y = 0; y < N; y++) for (int x = 0; x < N; x++) {
        float u = (float)x / N, v = (float)y / N;
        float r, g, b;
        if (which == 0) { r = 0.95f - 0.35f * v; g = 0.45f + 0.25f * u; b = 0.15f + 0.55f * v; }
        else { r = 0.10f + 0.25f * u; g = 0.55f + 0.30f * (1 - v); b = 0.85f - 0.25f * u; }
        bool grid = (x % 64 < 2) || (y % 64 < 2);
        if (grid) { r *= 0.78f; g *= 0.78f; b *= 0.78f; }
        float dx = u - 0.5f, dy = v - 0.5f, d = sqrtf(dx * dx + dy * dy);
        if (fabsf(d - 0.33f) < 0.012f) { r = g = b = 1.0f; }
        unsigned char* o = &px[(y * N + x) * 4];
        o[0] = (unsigned char)(r * 255); o[1] = (unsigned char)(g * 255); o[2] = (unsigned char)(b * 255); o[3] = 255;
    }
    // letter via GDI into a DIB, composited as white
    HDC dc = CreateCompatibleDC(nullptr);
    BITMAPINFO bi = {}; bi.bmiHeader.biSize = sizeof bi.bmiHeader; bi.bmiHeader.biWidth = N; bi.bmiHeader.biHeight = -N;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HBITMAP bmp = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ old = SelectObject(dc, bmp);
    memset(bits, 0, (size_t)N * N * 4);
    HFONT font = CreateFontW(-N / 2, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, L"Segoe UI");
    HGDIOBJ oldF = SelectObject(dc, font);
    SetBkMode(dc, TRANSPARENT); SetTextColor(dc, RGB(255, 255, 255));
    RECT rc = {0, 0, N, N};
    DrawTextW(dc, which == 0 ? L"A" : L"B", 1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    const unsigned char* g = (const unsigned char*)bits;
    for (int i = 0; i < N * N; i++) {
        float a = g[i * 4 + 1] / 255.0f;
        for (int c = 0; c < 3; c++) px[i * 4 + c] = (unsigned char)(px[i * 4 + c] * (1 - a) + 255 * a);
    }
    SelectObject(dc, oldF); DeleteObject(font); SelectObject(dc, old); DeleteObject(bmp); DeleteDC(dc);
    setImagePixels(which, px.data());
}

// Loads a picture with Windows' own decoders (PNG, JPEG, BMP, GIF, TIFF, WebP when the codec is installed),
// centre-cropped to a square and scaled to the preview size.
bool Renderer::loadImage(int which, const wchar_t* path, std::string& error) {
    IWICImagingFactory* f = nullptr;
    if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&f)))) { error = "image decoder unavailable"; return false; }
    IWICBitmapDecoder* dec = nullptr; IWICBitmapFrameDecode* frame = nullptr; IWICBitmapClipper* clip = nullptr;
    IWICBitmapScaler* scaler = nullptr; IWICFormatConverter* conv = nullptr;
    bool ok = false;
    do {
        if (FAILED(f->CreateDecoderFromFilename(path, nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &dec))) { error = "cannot open that picture"; break; }
        if (FAILED(dec->GetFrame(0, &frame))) { error = "cannot read that picture"; break; }
        UINT w = 0, h = 0; frame->GetSize(&w, &h);
        if (!w || !h) { error = "empty picture"; break; }
        UINT s = w < h ? w : h;
        WICRect r = {(INT)((w - s) / 2), (INT)((h - s) / 2), (INT)s, (INT)s};
        f->CreateBitmapClipper(&clip);
        if (FAILED(clip->Initialize(frame, &r))) { error = "cannot crop"; break; }
        f->CreateBitmapScaler(&scaler);
        if (FAILED(scaler->Initialize(clip, kPreview, kPreview, WICBitmapInterpolationModeHighQualityCubic))) { error = "cannot scale"; break; }
        f->CreateFormatConverter(&conv);
        if (FAILED(conv->Initialize(scaler, GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone, nullptr, 0, WICBitmapPaletteTypeCustom))) { error = "unsupported pixel format"; break; }
        std::vector<unsigned char> px((size_t)kPreview * kPreview * 4);
        if (FAILED(conv->CopyPixels(nullptr, kPreview * 4, (UINT)px.size(), px.data()))) { error = "cannot copy pixels"; break; }
        setImagePixels(which, px.data());
        ok = true;
    } while (0);
    rel(conv); rel(scaler); rel(clip); rel(frame); rel(dec); rel(f);
    return ok;
}
