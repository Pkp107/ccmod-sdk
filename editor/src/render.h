// Direct3D 11 side: the window's swap chain, the square preview target, the two sample/clip images and the transition shader.
#pragma once
#include <d3d11.h>
#include <string>
#include "codegen.h"
#include "model.h"

class Renderer {
public:
    static constexpr int kPreview = 768;                 // the preview is always a square (1:1) texture

    bool init(HWND hwnd, int w, int h);
    void shutdown();
    void resize(int w, int h);
    void beginFrame(const float clear[4]);
    void present();

    // transition preview
    bool compileShader(std::string& error);              // builds the HLSL from codegen (once at startup)
    void renderPreview(const Project& p, const Baked baked[kTracks], double progress);
    ID3D11ShaderResourceView* previewSRV() const { return previewSrv_; }

    // images (A = outgoing, B = incoming)
    void useSample(int which);                           // 0 = A, 1 = B
    bool loadImage(int which, const wchar_t* path, std::string& error);

    ID3D11Device* device() const { return dev_; }
    ID3D11DeviceContext* context() const { return ctx_; }

private:
    void createTargets();
    void releaseTargets();
    void setImagePixels(int which, const unsigned char* rgba);

    ID3D11Device* dev_ = nullptr;
    ID3D11DeviceContext* ctx_ = nullptr;
    IDXGISwapChain* swap_ = nullptr;
    ID3D11RenderTargetView* backRtv_ = nullptr;

    ID3D11Texture2D* previewTex_ = nullptr;
    ID3D11RenderTargetView* previewRtv_ = nullptr;
    ID3D11ShaderResourceView* previewSrv_ = nullptr;
    ID3D11VertexShader* vs_ = nullptr;
    ID3D11PixelShader* ps_ = nullptr;
    ID3D11Buffer* cb_ = nullptr;
    ID3D11SamplerState* samp_ = nullptr;
    ID3D11Texture2D* imgTex_[2] = {nullptr, nullptr};
    ID3D11ShaderResourceView* imgSrv_[2] = {nullptr, nullptr};
};
